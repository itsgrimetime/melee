"""Resolve one retail anchor to round-trip-stable allocator roles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .. import role_descriptor, role_matcher, role_reanchor
from ..parser import Instruction
from .backend_adapter import _operand_roles
from .canonical import stable_id
from .graph import FrontierGraph
from .models import ComparisonRecord, Confidence, EvidenceEdge, EvidenceNode, Provenance, min_confidence
from .object_binding_adapter import (
    ObjectBindingEvidence,
    exact_owner_path_record,
    proof_complete,
)

_REGISTER = re.compile(r"\b([rf])\d+\b")
_ADDI_ZERO_COPY = re.compile(
    r"^\s*r(?:\d+|#)\s*,\s*r(?P<source>\d+|#)\s*,\s*(?:0|0x0)\s*$",
    re.IGNORECASE,
)
_ASSERTION = re.compile(r"^(?P<label>[A-Za-z0-9_-]+):(?P<operand>(?:def|use):\d+)=(?P<spec>.+)$")
_CLASS_IG = re.compile(r"^(?P<class>0|1|gpr|fpr|r|f):(?P<ig>\d+)$", re.IGNORECASE)
_VIRTUAL = re.compile(r"^(?P<kind>[rf])(?P<number>\d+)$", re.IGNORECASE)
_PARSER_VERSION = "causal-anchor-alignment.v1"
_FIXED_GPRS = frozenset({1, 2})
_ZERO_BASE_OPERANDS: Mapping[str, frozenset[int]] = MappingProxyType(
    {
        "addi": frozenset({1}),
        "lhz": frozenset({1}),
        "lwz": frozenset({1}),
        "stwu": frozenset({1}),
        "stwux": frozenset({1}),
    }
)


class AbstentionReason(StrEnum):
    MISSING_RETAIL_ROW = "missing-retail-row"
    AMBIGUOUS_INSTRUCTION = "ambiguous-instruction-alignment"
    MISSING_BACKEND_ROLE = "missing-backend-role"
    AMBIGUOUS_BACKEND_ROLE = "ambiguous-backend-role"
    UNSTABLE_ROLE_IDENTITY = "unstable-role-identity"
    MISSING_EXPECTED_LAYOUT = "missing-expected-layout"
    CONTRADICTORY_EXPECTED_LAYOUT = "contradictory-expected-layout"
    UNSUPPORTED_OPCODE_SEMANTICS = "unsupported-opcode-semantics"
    AMBIGUOUS_STACK_OBJECT = "ambiguous-stack-object"


@dataclass(frozen=True, slots=True)
class OperandRole:
    key: str
    kind: Literal["def", "use"]
    position: int
    register_kind: Literal["r", "f"]
    expected_phys: int


@dataclass(frozen=True, slots=True)
class EffectAbstention:
    operand_key: str
    reason: AbstentionReason
    missing_capability_ids: tuple[str, ...] = ()
    missing_record_ids: tuple[str, ...] = ()
    follow_up_commands: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RolePair:
    operand_key: str
    left_label: str
    left: EvidenceNode
    right_label: str
    right: EvidenceNode
    comparison: ComparisonRecord
    asserted_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnchorAlignment:
    analysis_id: str
    retail_offset: int
    operand_roles: tuple[OperandRole, ...]
    by_operand: Mapping[str, RolePair]
    comparisons: tuple[ComparisonRecord, ...]
    abstentions: tuple[EffectAbstention, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_operand", MappingProxyType(dict(self.by_operand)))


@dataclass(frozen=True, slots=True)
class _OperandSemantics:
    roles: tuple[OperandRole, ...]
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class _LocalRoleResolution:
    node: EvidenceNode
    candidate: EvidenceNode | None
    pcode: EvidenceNode | None
    use_def_edge: EvidenceEdge | None
    virtual: EvidenceNode | None
    allocator_map_edge: EvidenceEdge | None
    confidence: Confidence
    asserted: bool = False
    verified_retail_path: bool = False
    supporting_records: tuple[EvidenceNode | EvidenceEdge, ...] = ()

    @property
    def evidence_chain(self) -> tuple[EvidenceNode | EvidenceEdge, ...]:
        return tuple(
            record
            for record in (
                self.candidate,
                self.pcode,
                self.use_def_edge,
                self.virtual,
                self.allocator_map_edge,
                self.node,
                *self.supporting_records,
            )
            if record is not None
        )


@dataclass(frozen=True, slots=True)
class BackendOwnerRoleTuple:
    operand_key: str
    register_class: str
    semantic_stack_role: str
    type_size: int
    frame_area: str

    def values(self) -> tuple[str, str, str, int, str]:
        return (
            self.operand_key,
            self.register_class,
            self.semantic_stack_role,
            self.type_size,
            self.frame_area,
        )


@dataclass(frozen=True, slots=True)
class BackendOwnerPath:
    evidence: ObjectBindingEvidence
    owner: EvidenceNode
    anchor: EvidenceNode
    pcode: EvidenceNode
    lineage: EvidenceNode
    virtual: EvidenceNode
    allocator: EvidenceNode
    stack: EvidenceNode
    supporting_records: tuple[EvidenceNode | EvidenceEdge, ...]

    @property
    def capture_run_id(self) -> str:
        return self.evidence.capture_run_id

    def semantic_state(self, role: BackendOwnerRoleTuple) -> Mapping[str, object]:
        """Project only cross-capture allocator/frame facts from this exact path."""

        return {
            "role_tuple": role.values(),
            "assigned_physical_register": self.allocator.attributes.get("assigned_phys"),
            "stack_offset": self.stack.attributes.get("offset"),
            "stack_size": self.stack.attributes.get("size"),
        }


@dataclass(frozen=True, slots=True)
class BackendOwnerCandidate:
    role_tuple: BackendOwnerRoleTuple
    left: BackendOwnerPath
    right: BackendOwnerPath


def _proof_edge(
    evidence: ObjectBindingEvidence,
    kind: str,
    source_id: str,
    target_id: str,
) -> tuple[EvidenceEdge, ...]:
    return tuple(
        edge
        for edge in evidence.edges
        if edge.kind == kind
        and edge.source_id == source_id
        and edge.target_id == target_id
        and exact_owner_path_record(evidence, edge)
    )


def _local_backend_owner_paths(
    evidence: ObjectBindingEvidence,
    role: BackendOwnerRoleTuple,
) -> tuple[BackendOwnerPath, ...]:
    if not proof_complete(evidence):
        return ()
    nodes = {node.record_id: node for node in evidence.nodes}
    register_class_id = 1 if role.register_class in {"f", "fpr"} else 0
    paths: list[BackendOwnerPath] = []
    anchors = tuple(
        node
        for node in evidence.nodes
        if node.kind == "assembly-operand-anchor"
        and node.attributes.get("machine_operand_key") == role.operand_key
        and exact_owner_path_record(evidence, node)
    )
    owners = tuple(
        node
        for node in evidence.nodes
        if node.kind == "compiler-object"
        and node.attributes.get("type_size") == role.type_size
        and role.frame_area in node.attributes.get("areas", ())
        and exact_owner_path_record(evidence, node)
    )
    for anchor in anchors:
        # Preserve every exact alternative rather than selecting by numeric identity.
        anchor_edges = tuple(
            edge
            for edge in evidence.edges
            if edge.kind == "assembly-anchor-emitted-by-pcode"
            and edge.source_id == anchor.record_id
            and edge.target_id in nodes
            and exact_owner_path_record(evidence, edge)
        )
        for anchor_edge in anchor_edges:
            pcode = nodes[anchor_edge.target_id]
            if not exact_owner_path_record(evidence, pcode):
                continue
            lineage_edges = tuple(
                edge
                for edge in evidence.edges
                if edge.kind == "pcode-operand-lineage"
                and edge.source_id == pcode.record_id
                and edge.target_id in nodes
                and exact_owner_path_record(evidence, edge)
            )
            for lineage_edge in lineage_edges:
                lineage = nodes[lineage_edge.target_id]
                if not exact_owner_path_record(evidence, lineage):
                    continue
                virtual_edges = tuple(
                    edge
                    for edge in evidence.edges
                    if edge.kind == "pcode-operand-uses-virtual"
                    and edge.source_id == lineage.record_id
                    and edge.target_id in nodes
                    and exact_owner_path_record(evidence, edge)
                )
                for virtual_edge in virtual_edges:
                    virtual = nodes[virtual_edge.target_id]
                    if virtual.attributes.get("class_id") != register_class_id or not exact_owner_path_record(
                        evidence, virtual
                    ):
                        continue
                    allocator_edges = tuple(
                        edge
                        for edge in evidence.edges
                        if edge.kind == "maps-to-allocator-node"
                        and edge.source_id == virtual.record_id
                        and edge.target_id in nodes
                        and exact_owner_path_record(evidence, edge)
                    )
                    for owner in owners:
                        object_edges = _proof_edge(
                            evidence,
                            "object-materializes-virtual",
                            owner.record_id,
                            virtual.record_id,
                        )
                        stack_edges = tuple(
                            edge
                            for edge in evidence.edges
                            if edge.kind == "object-has-stack-home"
                            and edge.source_id == owner.record_id
                            and edge.target_id in nodes
                            and edge.attributes.get("area") == role.frame_area
                            and edge.attributes.get("semantic_stack_role") == role.semantic_stack_role
                            and exact_owner_path_record(evidence, edge)
                        )
                        for object_edge in object_edges:
                            for allocator_edge in allocator_edges:
                                allocator = nodes[allocator_edge.target_id]
                                if not exact_owner_path_record(evidence, allocator):
                                    continue
                                for stack_edge in stack_edges:
                                    stack = nodes[stack_edge.target_id]
                                    if not exact_owner_path_record(evidence, stack):
                                        continue
                                    supporting = (
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
                                        stack_edge,
                                        stack,
                                    )
                                    if all(exact_owner_path_record(evidence, record) for record in supporting):
                                        paths.append(
                                            BackendOwnerPath(
                                                evidence,
                                                owner,
                                                anchor,
                                                pcode,
                                                lineage,
                                                virtual,
                                                allocator,
                                                stack,
                                                supporting,
                                            )
                                        )
    return tuple(
        sorted(
            paths,
            key=lambda path: (
                path.owner.record_id,
                path.anchor.record_id,
                path.stack.record_id,
                tuple(record.record_id for record in path.supporting_records),
            ),
        )
    )


def resolve_backend_owner_candidates(
    evidence_pair: tuple[ObjectBindingEvidence, ObjectBindingEvidence],
    role_tuple: BackendOwnerRoleTuple,
) -> tuple[BackendOwnerCandidate, ...]:
    """Enumerate every semantic bilateral owner without cross-run identities."""

    left, right = evidence_pair
    left_paths = _local_backend_owner_paths(left, role_tuple)
    right_paths = _local_backend_owner_paths(right, role_tuple)
    return tuple(
        BackendOwnerCandidate(role_tuple, left_path, right_path)
        for left_path in left_paths
        for right_path in right_paths
    )


def backend_owner_correspondences(
    analysis_id: str,
    candidates: tuple[BackendOwnerCandidate, ...],
) -> tuple[ComparisonRecord, ...]:
    """Render analysis-scoped semantic owner alternatives, never graph edges."""

    unique = len(candidates) == 1
    comparisons: list[ComparisonRecord] = []
    for ordinal, candidate in enumerate(candidates):
        inputs = (
            *candidate.left.supporting_records,
            *candidate.right.supporting_records,
        )
        left_path_proof_complete = all(
            exact_owner_path_record(candidate.left.evidence, record) for record in candidate.left.supporting_records
        )
        right_path_proof_complete = all(
            exact_owner_path_record(candidate.right.evidence, record) for record in candidate.right.supporting_records
        )
        confidence = min_confidence(*(record.confidence for record in inputs)) if unique else Confidence.HEURISTIC
        comparisons.append(
            ComparisonRecord.create(
                analysis_id=analysis_id,
                relation_kind="backend-owner-corresponds-to",
                left_compile_id=candidate.left.owner.compile_id,
                left_record_id=candidate.left.owner.record_id,
                right_compile_id=candidate.right.owner.compile_id,
                right_record_id=candidate.right.owner.record_id,
                producer_confidence=confidence,
                adapter_confidence=confidence,
                provenance=Provenance(
                    artifact_sha256=analysis_id,
                    parser="causal-backend-owner-alignment.v1",
                    raw_start=None,
                    raw_end=None,
                    derivation_rule=(
                        "semantic-owner-role-tuple:" + ":".join(str(value) for value in candidate.role_tuple.values())
                    ),
                    input_record_ids=tuple(record.record_id for record in inputs),
                ),
                input_confidences=tuple(record.confidence for record in inputs),
                occurrence_ordinal=ordinal,
                attributes={
                    "role_tuple": candidate.role_tuple.values(),
                    "left_semantic_state": candidate.left.semantic_state(candidate.role_tuple),
                    "right_semantic_state": candidate.right.semantic_state(candidate.role_tuple),
                    "alternative_count": len(candidates),
                    "left_path_proof_complete": left_path_proof_complete,
                    "right_path_proof_complete": right_path_proof_complete,
                    "proof_complete": unique and left_path_proof_complete and right_path_proof_complete,
                    "scope": "analysis",
                },
            )
        )
    return tuple(comparisons)


def _label(graph: FrontierGraph) -> str:
    return str(graph.bundle.label)


def _compile_id(graph: FrontierGraph) -> str:
    return str(graph.bundle.compile_id)


def _normalized_instruction(opcode: object, operands: object) -> str:
    normalized_opcode = str(opcode).lower()
    raw_operands = str(operands).lower()
    copy_match = _ADDI_ZERO_COPY.fullmatch(raw_operands)
    if normalized_opcode == "addi" and copy_match is not None and copy_match.group("source") != "0":
        normalized_opcode = "mr"
        raw_operands = raw_operands.rsplit(",", 1)[0]
    normalized_operands = _REGISTER.sub(lambda match: f"{match.group(1).lower()}#", raw_operands)
    normalized_operands = re.sub(r"\s+", "", normalized_operands)
    return f"{normalized_opcode} {normalized_operands}".rstrip()


def _normalized_instruction_text(value: object) -> str:
    opcode, separator, operands = str(value).strip().partition(" ")
    return _normalized_instruction(opcode, operands if separator else "")


def _pcode_neighborhoods(graph: FrontierGraph) -> Mapping[str, tuple[str, ...]]:
    groups: dict[int, list[EvidenceNode]] = {}
    for node in graph.store.find_nodes(_compile_id(graph), "pcode-occurrence"):
        pass_index = node.attributes.get("pass_index")
        if isinstance(pass_index, int):
            groups.setdefault(pass_index, []).append(node)
    neighborhoods: dict[str, tuple[str, ...]] = {}
    for nodes in groups.values():
        ordered = sorted(
            nodes,
            key=lambda node: (
                int(node.attributes.get("block", -1)),
                int(node.attributes.get("instruction_index", -1)),
                node.record_id,
            ),
        )
        signatures = [
            _normalized_instruction(node.attributes.get("opcode"), node.attributes.get("operands")) for node in ordered
        ]
        for index, node in enumerate(ordered):
            neighborhoods[node.record_id] = tuple(signatures[max(0, index - 1) : index + 2])
    return MappingProxyType(neighborhoods)


def _allocatable_operand(opcode: str, raw_position: int, register_kind: str, physical: int) -> bool:
    if register_kind != "r":
        return True
    if physical in _FIXED_GPRS:
        return False
    return not (physical == 0 and raw_position in _ZERO_BASE_OPERANDS.get(opcode.lower(), ()))


def _parse_assertions(
    assertions: Iterable[str], labels: frozenset[str]
) -> tuple[tuple[str, ...], Mapping[tuple[str, str], str]]:
    normalized: dict[tuple[str, str], str] = {}
    rendered: list[str] = []
    for raw in assertions:
        value = raw.strip()
        match = _ASSERTION.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid frontier-node assertion: {raw!r}")
        label, operand, spec = match.group("label", "operand", "spec")
        if label not in labels:
            raise ValueError(f"frontier-node assertion names unknown label: {label}")
        key = (label, operand)
        if key in normalized:
            raise ValueError(f"duplicate frontier-node assertion: {label}:{operand}")
        normalized[key] = spec.strip()
        rendered.append(f"{label}:{operand}={spec.strip()}")
    return tuple(sorted(rendered)), MappingProxyType(normalized)


def _analysis_id(graphs: tuple[FrontierGraph, FrontierGraph], retail_offset: int, assertions: tuple[str, ...]) -> str:
    frontiers = tuple(sorted((_label(graph), _compile_id(graph)) for graph in graphs))
    return stable_id(
        "causal-analysis",
        "anchor-alignment",
        {"frontiers": frontiers, "retail_offset": retail_offset, "assertions": assertions},
    )


def _operand_roles_for_graph(graph: FrontierGraph, retail_offset: int) -> _OperandSemantics:
    row = graph.checkdiff.rows_by_offset.get(retail_offset)
    if row is None:
        return _OperandSemantics((), Confidence.HEURISTIC)
    instruction = Instruction(
        opcode=row.expected.opcode,
        operands=row.expected.operands,
        annotations=[],
        regs=list(row.expected.regs),
    )
    roles_by_operand, confidence = _operand_roles(instruction, "mwcc-debug-pcdump.v1")
    semantic_entries: list[tuple[str, int, str, int]] = []
    for raw_position, ((register_kind, expected_phys), semantics) in enumerate(
        zip(row.expected.regs, roles_by_operand)
    ):
        if not _allocatable_operand(row.expected.opcode, raw_position, register_kind, expected_phys):
            continue
        for kind in ("def", "use"):
            if kind in semantics:
                semantic_entries.append((kind, raw_position, register_kind, expected_phys))
    semantic_entries.sort(key=lambda item: (0 if item[0] == "def" else 1, item[1]))
    positions = {"def": 0, "use": 0}
    roles: list[OperandRole] = []
    for kind, _raw_position, register_kind, expected_phys in semantic_entries:
        position = positions[kind]
        positions[kind] += 1
        roles.append(
            OperandRole(
                key=f"{kind}:{position}",
                kind=kind,
                position=position,
                register_kind=register_kind,
                expected_phys=expected_phys,
            )
        )
    return _OperandSemantics(tuple(roles), confidence)


def _raw_operand_position(graph: FrontierGraph, retail_offset: int, role: OperandRole) -> int | None:
    row = graph.checkdiff.rows_by_offset.get(retail_offset)
    if row is None:
        return None
    instruction = Instruction(
        opcode=row.expected.opcode,
        operands=row.expected.operands,
        annotations=[],
        regs=list(row.expected.regs),
    )
    roles_by_operand, _confidence = _operand_roles(instruction, "mwcc-debug-pcdump.v1")
    seen = 0
    for raw_position, ((register_kind, expected_phys), semantics) in enumerate(
        zip(row.expected.regs, roles_by_operand)
    ):
        if not _allocatable_operand(row.expected.opcode, raw_position, register_kind, expected_phys):
            continue
        if role.kind not in semantics:
            continue
        if seen == role.position:
            return raw_position
        seen += 1
    return None


def _candidate_is_uniquely_aligned(graph: FrontierGraph, retail_offset: int) -> EvidenceNode | None:
    compile_id = _compile_id(graph)
    candidates = tuple(
        node
        for node in graph.store.find_nodes(compile_id, "candidate-instruction")
        if node.attributes.get("aligned_retail_offset") == retail_offset
    )
    retails = tuple(
        node
        for node in graph.store.find_nodes(compile_id, "retail-instruction")
        if node.attributes.get("offset") == retail_offset
    )
    if len(candidates) != 1 or len(retails) != 1:
        return None
    candidate, retail = candidates[0], retails[0]
    if candidate.attributes.get("retail_neighborhood_signature") != retail.attributes.get("neighborhood_signature"):
        return None
    alignments = tuple(
        edge
        for edge in graph.store.find_edges(compile_id, "aligns-to-retail", endpoint=candidate.record_id)
        if edge.source_id == candidate.record_id
        and edge.target_id == retail.record_id
        and edge.attributes.get("retail_offset") == retail_offset
    )
    return candidate if len(alignments) == 1 else None


def _allocator_from_virtual(graph: FrontierGraph, virtual_id: str) -> tuple[tuple[EvidenceEdge, EvidenceNode], ...]:
    compile_id = _compile_id(graph)
    mappings = {
        edge.target_id: edge
        for edge in graph.store.find_edges(compile_id, "maps-to-allocator-node", endpoint=virtual_id)
        if edge.source_id == virtual_id
    }
    return tuple(
        (mappings[record_id], node)
        for record_id in sorted(mappings)
        if (node := graph.store.get_node(record_id)) is not None and node.kind == "allocator-node"
    )


def _verified_retail_local_role(
    graph: FrontierGraph,
    candidate: EvidenceNode,
    retail_offset: int,
    role: OperandRole,
) -> tuple[_LocalRoleResolution | None, AbstentionReason]:
    evidence = graph.backend.object_bindings
    if evidence is None or not proof_complete(evidence):
        return None, AbstentionReason.MISSING_BACKEND_ROLE
    nodes = {node.record_id: node for node in evidence.nodes}

    def edges(kind: str, source_id: str) -> tuple[EvidenceEdge, ...]:
        return tuple(
            edge
            for edge in evidence.edges
            if edge.kind == kind
            and edge.source_id == source_id
            and edge.target_id in nodes
            and exact_owner_path_record(evidence, edge)
        )

    alternatives: dict[str, list[_LocalRoleResolution]] = {}
    anchors = tuple(
        node
        for node in evidence.nodes
        if node.kind == "assembly-operand-anchor"
        and node.attributes.get("code_offset") == retail_offset
        and node.attributes.get("machine_operand_key") == role.key
        and exact_owner_path_record(evidence, node)
    )
    class_id = 1 if role.register_kind == "f" else 0
    for anchor in anchors:
        for anchor_edge in edges("assembly-anchor-emitted-by-pcode", anchor.record_id):
            pcode = nodes[anchor_edge.target_id]
            for lineage_edge in edges("pcode-operand-lineage", pcode.record_id):
                lineage = nodes[lineage_edge.target_id]
                for virtual_edge in edges("pcode-operand-uses-virtual", lineage.record_id):
                    virtual = nodes[virtual_edge.target_id]
                    if virtual.attributes.get("class_id") != class_id:
                        continue
                    for allocator_edge in edges("maps-to-allocator-node", virtual.record_id):
                        allocator = nodes[allocator_edge.target_id]
                        supporting = (
                            anchor,
                            anchor_edge,
                            lineage_edge,
                            lineage,
                        )
                        chain = (
                            candidate,
                            pcode,
                            virtual_edge,
                            virtual,
                            allocator_edge,
                            allocator,
                            *supporting,
                        )
                        selected_v2_path = tuple(record for record in chain if record is not candidate)
                        if not all(
                            exact_owner_path_record(evidence, record) for record in selected_v2_path
                        ) or not proof_complete(
                            evidence,
                            frozenset(record.record_id for record in selected_v2_path),
                        ):
                            continue
                        alternatives.setdefault(allocator.record_id, []).append(
                            _LocalRoleResolution(
                                node=allocator,
                                candidate=candidate,
                                pcode=pcode,
                                use_def_edge=virtual_edge,
                                virtual=virtual,
                                allocator_map_edge=allocator_edge,
                                confidence=min_confidence(*(record.confidence for record in chain)),
                                verified_retail_path=True,
                                supporting_records=supporting,
                            )
                        )
    if len(alternatives) == 1:
        return next(iter(alternatives.values()))[0], AbstentionReason.MISSING_BACKEND_ROLE
    if alternatives:
        return None, AbstentionReason.AMBIGUOUS_BACKEND_ROLE
    return None, AbstentionReason.MISSING_BACKEND_ROLE


def _automatic_local_role(
    graph: FrontierGraph, retail_offset: int, role: OperandRole
) -> tuple[_LocalRoleResolution | None, AbstentionReason]:
    candidate = _candidate_is_uniquely_aligned(graph, retail_offset)
    if candidate is None:
        return None, AbstentionReason.AMBIGUOUS_INSTRUCTION
    raw_position = _raw_operand_position(graph, retail_offset, role)
    if raw_position is None:
        return None, AbstentionReason.MISSING_BACKEND_ROLE
    verified, verified_reason = _verified_retail_local_role(graph, candidate, retail_offset, role)
    if verified is not None or verified_reason is AbstentionReason.AMBIGUOUS_BACKEND_ROLE:
        return verified, verified_reason
    signature = _normalized_instruction(candidate.attributes.get("opcode"), candidate.attributes.get("operands"))
    expected_neighborhood = tuple(
        _normalized_instruction_text(item) for item in candidate.attributes.get("retail_neighborhood_signature", ())
    )
    pcode_neighborhoods = _pcode_neighborhoods(graph)
    edge_kind = "defines-virtual" if role.kind == "def" else "uses-virtual"
    resolutions: dict[str, list[_LocalRoleResolution]] = {}
    for occurrence in graph.store.find_nodes(_compile_id(graph), "pcode-occurrence"):
        if (
            _normalized_instruction(occurrence.attributes.get("opcode"), occurrence.attributes.get("operands"))
            != signature
        ):
            continue
        if len(expected_neighborhood) > 1 and pcode_neighborhoods.get(occurrence.record_id) != expected_neighborhood:
            continue
        edges = tuple(
            edge
            for edge in graph.store.find_edges(_compile_id(graph), edge_kind, endpoint=occurrence.record_id)
            if edge.source_id == occurrence.record_id and edge.attributes.get("operand_position") == raw_position
        )
        for edge in edges:
            virtual = graph.store.get_node(edge.target_id)
            if virtual is None or virtual.kind != "virtual-register":
                continue
            for map_edge, allocator in _allocator_from_virtual(graph, edge.target_id):
                class_id = 1 if role.register_kind == "f" else 0
                if allocator.attributes.get("class_id") == class_id:
                    chain = (candidate, occurrence, edge, virtual, map_edge, allocator)
                    resolutions.setdefault(allocator.record_id, []).append(
                        _LocalRoleResolution(
                            node=allocator,
                            candidate=candidate,
                            pcode=occurrence,
                            use_def_edge=edge,
                            virtual=virtual,
                            allocator_map_edge=map_edge,
                            confidence=min_confidence(*(record.confidence for record in chain)),
                        )
                    )
    if len(resolutions) == 1:
        choices = next(iter(resolutions.values()))
        selected = max(
            choices,
            key=lambda item: (
                int(item.pcode.attributes.get("pass_index", -1)) if item.pcode is not None else -1,
                int(item.pcode.attributes.get("instruction_index", -1)) if item.pcode is not None else -1,
                item.pcode.record_id if item.pcode is not None else "",
            ),
        )
        return selected, AbstentionReason.MISSING_BACKEND_ROLE
    if resolutions:
        return None, AbstentionReason.AMBIGUOUS_BACKEND_ROLE
    return None, AbstentionReason.MISSING_BACKEND_ROLE


def _asserted_local_role(graph: FrontierGraph, spec: str) -> _LocalRoleResolution:
    class_match = _CLASS_IG.fullmatch(spec)
    if class_match is not None:
        class_text = class_match.group("class").lower()
        class_id = 1 if class_text in {"1", "f", "fpr"} else 0
        record_id = graph.backend.nodes_by_class_ig.get((class_id, int(class_match.group("ig"))))
    else:
        virtual_match = _VIRTUAL.fullmatch(spec)
        if virtual_match is None:
            raise ValueError(f"invalid frontier-node spec: {spec!r}")
        kind = virtual_match.group("kind").lower()
        virtual_id = graph.backend.nodes_by_virtual.get((kind, int(virtual_match.group("number"))))
        candidates = () if virtual_id is None else _allocator_from_virtual(graph, virtual_id)
        if len(candidates) != 1:
            raise ValueError(f"frontier-node virtual assertion is not unique: {spec!r}")
        map_edge, node = candidates[0]
        virtual = None if virtual_id is None else graph.store.get_node(virtual_id)
        return _LocalRoleResolution(
            node=node,
            candidate=None,
            pcode=None,
            use_def_edge=None,
            virtual=virtual,
            allocator_map_edge=map_edge,
            confidence=Confidence.HEURISTIC,
            asserted=True,
        )
    node = None if record_id is None else graph.store.get_node(record_id)
    if node is None or node.kind != "allocator-node":
        raise ValueError(f"frontier-node assertion does not resolve to an allocator node: {spec!r}")
    return _LocalRoleResolution(
        node=node,
        candidate=None,
        pcode=None,
        use_def_edge=None,
        virtual=None,
        allocator_map_edge=None,
        confidence=Confidence.HEURISTIC,
        asserted=True,
    )


def _abstention(operand_key: str, reason: AbstentionReason) -> EffectAbstention:
    missing_capabilities = (
        ("virtual-use-def", "virtual-to-allocator-node")
        if reason in {AbstentionReason.MISSING_BACKEND_ROLE, AbstentionReason.AMBIGUOUS_BACKEND_ROLE}
        else ()
    )
    return EffectAbstention(
        operand_key=operand_key,
        reason=reason,
        missing_capability_ids=missing_capabilities,
        follow_up_commands=(
            "melee-agent debug inspect virtual-to-ig --help",
            "melee-agent debug target reanchor --help",
        ),
    )


def _role_comparison(
    *,
    analysis_id: str,
    role: OperandRole,
    left_graph: FrontierGraph,
    left: _LocalRoleResolution,
    right_graph: FrontierGraph,
    right: _LocalRoleResolution,
    ordinal: int,
) -> ComparisonRecord:
    asserted_labels = tuple(
        label for label, local in ((_label(left_graph), left), (_label(right_graph), right)) if local.asserted
    )
    verified_retail = left.verified_retail_path and right.verified_retail_path
    confidence = Confidence.HEURISTIC if asserted_labels else min_confidence(left.confidence, right.confidence)
    inputs = (*left.evidence_chain, *right.evidence_chain)
    return ComparisonRecord.create(
        analysis_id=analysis_id,
        relation_kind="role-corresponds-to",
        left_compile_id=_compile_id(left_graph),
        left_record_id=left.node.record_id,
        right_compile_id=_compile_id(right_graph),
        right_record_id=right.node.record_id,
        producer_confidence=confidence,
        adapter_confidence=confidence,
        provenance=Provenance(
            artifact_sha256=analysis_id,
            parser=_PARSER_VERSION,
            raw_start=None,
            raw_end=None,
            derivation_rule=(
                "operand-scoped-expert-assertion"
                if asserted_labels
                else (
                    "verified-retail-semantic-operand-role" if verified_retail else "round-trip-role-descriptor-match"
                )
            ),
            input_record_ids=tuple(node.record_id for node in inputs),
        ),
        input_confidences=tuple(node.confidence for node in inputs),
        occurrence_ordinal=ordinal,
        attributes={
            "operand_key": role.key,
            "expected_phys": role.expected_phys,
            "register_kind": role.register_kind,
            "left_ig": left.node.attributes.get("ig_id"),
            "right_ig": right.node.attributes.get("ig_id"),
            "expert_assertion": bool(asserted_labels),
            "asserted_labels": asserted_labels,
            "verdict_cap": "candidate-cause" if asserted_labels else None,
            "identity_mode": ("verified-retail-semantic-role" if verified_retail else "round-trip-role-descriptor"),
        },
    )


def _round_trip_matches(
    left_graph: FrontierGraph,
    left: EvidenceNode,
    right_graph: FrontierGraph,
    right: EvidenceNode,
    expected_phys: int,
) -> bool:
    left_class = left.attributes.get("class_id")
    right_class = right.attributes.get("class_id")
    left_ig = left.attributes.get("ig_id")
    right_ig = right.attributes.get("ig_id")
    if not all(isinstance(item, int) for item in (left_class, right_class, left_ig, right_ig)):
        return False
    if left_class != right_class:
        return False
    if left_graph.backend.role_compile is None or right_graph.backend.role_compile is None:
        return False
    left_descs = role_descriptor.build_descriptors(left_graph.backend.role_compile, left_class)
    right_descs = role_descriptor.build_descriptors(right_graph.backend.role_compile, right_class)
    forward = role_matcher.match_roles(left_descs, right_descs)
    inverse = role_matcher.match_roles(right_descs, left_descs)
    _force_phys, _diagnostics, matched = role_reanchor._confirm_round_trip(forward, inverse, {left_ig: expected_phys})
    return matched.get(right_ig) == left_ig


def align_anchor(
    graphs: Iterable[FrontierGraph],
    retail_offset: int,
    assertions: Iterable[str],
) -> AnchorAlignment:
    """Align one retail instruction across exactly two labeled frontiers."""

    graph_pair = tuple(graphs)
    if len(graph_pair) != 2:
        raise ValueError("anchor alignment requires exactly two frontiers")
    if retail_offset < 0:
        raise ValueError("retail offset must be nonnegative")
    labels = tuple(_label(graph) for graph in graph_pair)
    if len(set(labels)) != 2:
        raise ValueError("frontier labels must be unique")
    normalized_assertions, assertions_by_key = _parse_assertions(assertions, frozenset(labels))
    ordered = tuple(sorted(graph_pair, key=_label))
    left_graph, right_graph = ordered
    analysis_id = _analysis_id((left_graph, right_graph), retail_offset, normalized_assertions)

    left_semantics = _operand_roles_for_graph(left_graph, retail_offset)
    right_semantics = _operand_roles_for_graph(right_graph, retail_offset)
    left_roles = left_semantics.roles
    right_roles = right_semantics.roles
    if not left_roles or not right_roles or left_roles != right_roles:
        return AnchorAlignment(
            analysis_id=analysis_id,
            retail_offset=retail_offset,
            operand_roles=left_roles or right_roles,
            by_operand={},
            comparisons=(),
            abstentions=(_abstention("anchor", AbstentionReason.MISSING_RETAIL_ROW),),
        )
    if Confidence.HEURISTIC in {left_semantics.confidence, right_semantics.confidence}:
        return AnchorAlignment(
            analysis_id=analysis_id,
            retail_offset=retail_offset,
            operand_roles=left_roles,
            by_operand={},
            comparisons=(),
            abstentions=tuple(
                _abstention(role.key, AbstentionReason.UNSUPPORTED_OPCODE_SEMANTICS) for role in left_roles
            ),
        )
    operand_keys = {role.key for role in left_roles}
    unknown_assertions = sorted(
        f"{label}:{operand}" for label, operand in assertions_by_key if operand not in operand_keys
    )
    if unknown_assertions:
        raise ValueError(
            "frontier-node assertion names operand not present on retail anchor: " + ", ".join(unknown_assertions)
        )

    by_operand: dict[str, RolePair] = {}
    comparisons: list[ComparisonRecord] = []
    abstentions: list[EffectAbstention] = []
    for ordinal, role in enumerate(left_roles):
        locals_by_label: dict[str, _LocalRoleResolution | None] = {}
        reasons: list[AbstentionReason] = []
        for graph in ordered:
            automatic, reason = _automatic_local_role(graph, retail_offset, role)
            spec = assertions_by_key.get((_label(graph), role.key))
            if spec is not None:
                asserted = _asserted_local_role(graph, spec)
                if automatic is not None and automatic.node.record_id != asserted.node.record_id:
                    raise ValueError(
                        f"frontier-node assertion contradicts unique automatic role: {_label(graph)}:{role.key}"
                    )
                locals_by_label[_label(graph)] = asserted
            else:
                locals_by_label[_label(graph)] = automatic
                if automatic is None:
                    reasons.append(reason)
        left = locals_by_label[_label(left_graph)]
        right = locals_by_label[_label(right_graph)]
        if left is None or right is None:
            abstentions.append(_abstention(role.key, reasons[0] if reasons else AbstentionReason.MISSING_BACKEND_ROLE))
            continue
        verified_retail_pair = left.verified_retail_path and right.verified_retail_path
        if not (left.asserted or right.asserted or verified_retail_pair) and not _round_trip_matches(
            left_graph, left.node, right_graph, right.node, role.expected_phys
        ):
            abstentions.append(_abstention(role.key, AbstentionReason.UNSTABLE_ROLE_IDENTITY))
            continue
        comparison = _role_comparison(
            analysis_id=analysis_id,
            role=role,
            left_graph=left_graph,
            left=left,
            right_graph=right_graph,
            right=right,
            ordinal=ordinal,
        )
        pair = RolePair(
            operand_key=role.key,
            left_label=_label(left_graph),
            left=left.node,
            right_label=_label(right_graph),
            right=right.node,
            comparison=comparison,
            asserted_labels=tuple(comparison.attributes.get("asserted_labels", ())),
        )
        by_operand[role.key] = pair
        comparisons.append(comparison)

    return AnchorAlignment(
        analysis_id=analysis_id,
        retail_offset=retail_offset,
        operand_roles=left_roles,
        by_operand=by_operand,
        comparisons=tuple(comparisons),
        abstentions=tuple(abstentions),
    )


def build_role_comparisons(alignment: AnchorAlignment, graphs: Iterable[FrontierGraph]) -> tuple[ComparisonRecord, ...]:
    """Return the alignment's comparison-scoped correspondences after scope validation."""

    graph_pair = tuple(graphs)
    if len(graph_pair) != 2:
        raise ValueError("role comparisons require exactly two frontiers")
    expected = tuple(sorted((_label(graph), _compile_id(graph)) for graph in graph_pair))
    for comparison in alignment.comparisons:
        actual = (
            (alignment.by_operand[str(comparison.attributes["operand_key"])].left_label, comparison.left_compile_id),
            (alignment.by_operand[str(comparison.attributes["operand_key"])].right_label, comparison.right_compile_id),
        )
        if actual != expected:
            raise ValueError("role comparison scope does not match frontier pair")
    comparisons = list(alignment.comparisons)
    ordered_graphs = tuple(sorted(graph_pair, key=_label))
    left_evidence = ordered_graphs[0].backend.object_bindings
    right_evidence = ordered_graphs[1].backend.object_bindings
    if left_evidence is None or right_evidence is None:
        return tuple(comparisons)

    def role_shapes(evidence: ObjectBindingEvidence) -> frozenset[tuple[str, int, str]]:
        nodes = {node.record_id: node for node in evidence.nodes}
        values: set[tuple[str, int, str]] = set()
        for edge in evidence.edges:
            if edge.kind != "object-has-stack-home":
                continue
            owner = nodes.get(edge.source_id)
            if owner is None or owner.kind != "compiler-object":
                continue
            semantic_role = edge.attributes.get("semantic_stack_role")
            type_size = owner.attributes.get("type_size")
            area = edge.attributes.get("area")
            if (
                isinstance(semantic_role, str)
                and semantic_role
                and isinstance(type_size, int)
                and not isinstance(type_size, bool)
                and isinstance(area, str)
                and area
            ):
                values.add((semantic_role, type_size, area))
        return frozenset(values)

    shared_shapes = role_shapes(left_evidence) & role_shapes(right_evidence)
    for operand in alignment.operand_roles:
        register_class = "fpr" if operand.register_kind == "f" else "gpr"
        for semantic_role, type_size, area in sorted(shared_shapes):
            role_tuple = BackendOwnerRoleTuple(
                operand.key,
                register_class,
                semantic_role,
                type_size,
                area,
            )
            candidates = resolve_backend_owner_candidates((left_evidence, right_evidence), role_tuple)
            comparisons.extend(backend_owner_correspondences(alignment.analysis_id, candidates))
    return tuple(comparisons)


__all__ = [
    "AbstentionReason",
    "AnchorAlignment",
    "BackendOwnerCandidate",
    "BackendOwnerPath",
    "BackendOwnerRoleTuple",
    "EffectAbstention",
    "OperandRole",
    "RolePair",
    "align_anchor",
    "backend_owner_correspondences",
    "build_role_comparisons",
    "resolve_backend_owner_candidates",
]
