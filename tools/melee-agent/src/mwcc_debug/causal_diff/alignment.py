"""Resolve one retail anchor to round-trip-stable allocator roles."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .. import role_descriptor, role_matcher, role_reanchor
from ..parser import Instruction
from .backend_adapter import _operand_roles
from .canonical import canonical_bytes, stable_id
from .graph import FrontierGraph
from .legacy_ownership import (
    legacy_allocator_chains_from_occurrence,
    legacy_allocator_from_virtual,
    legacy_pcode_occurrences,
)
from .models import ComparisonRecord, Confidence, EvidenceEdge, EvidenceNode, Provenance, min_confidence
from .owner_certificate import (
    OwnerCertificateRejection,
    OwnerCertificateResult,
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerRoleResolution,
    OwnerSemanticState,
)
from .store import canonical_record_bytes

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


def _verified_retail_local_role(
    graph: FrontierGraph,
    candidate: EvidenceNode,
    retail_offset: int,
    role: OperandRole,
) -> tuple[_LocalRoleResolution | None, AbstentionReason]:
    del retail_offset
    result = graph.backend.owner_certificates
    if not result.is_trusted:
        return None, AbstentionReason.MISSING_BACKEND_ROLE
    register_class = "fpr" if role.register_kind == "f" else "gpr"
    alternatives: dict[str, list[_LocalRoleResolution]] = {}
    for base_resolution in result.role_resolutions:
        owner_role = base_resolution.role
        if owner_role.operand_key != role.key or owner_role.register_class != register_class:
            continue
        resolution = result.resolution_for(owner_role)
        if resolution.status is not OwnerResolutionStatus.UNIQUE:
            continue
        for certificate_id in resolution.certificate_record_ids:
            certificate = _stored_certificate(graph, result, owner_role, certificate_id)
            if certificate is None:
                continue
            allocator_id = certificate.attributes.get("allocator_record_id")
            if not isinstance(allocator_id, str):
                continue
            allocator = _certificate_bound_node(
                graph,
                result,
                certificate,
                allocator_id,
                "allocator-node",
            )
            if allocator is None:
                continue
            pcode_id = certificate.attributes.get("pcode_record_id")
            virtual_id = certificate.attributes.get("virtual_record_id")
            pcode = (
                _certificate_bound_node(
                    graph,
                    result,
                    certificate,
                    pcode_id,
                    "retail-pcode",
                )
                if isinstance(pcode_id, str)
                else None
            )
            virtual = (
                _certificate_bound_node(
                    graph,
                    result,
                    certificate,
                    virtual_id,
                    "retail-virtual-register",
                )
                if isinstance(virtual_id, str)
                else None
            )
            if pcode is None or virtual is None:
                continue
            chain = tuple(
                record for record in (candidate, pcode, virtual, allocator, certificate) if record is not None
            )
            alternatives.setdefault(allocator.record_id, []).append(
                _LocalRoleResolution(
                    node=allocator,
                    candidate=candidate,
                    pcode=pcode,
                    use_def_edge=None,
                    virtual=virtual,
                    allocator_map_edge=None,
                    confidence=min_confidence(*(record.confidence for record in chain)),
                    verified_retail_path=True,
                    supporting_records=(certificate,),
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
    for occurrence in legacy_pcode_occurrences(graph):
        if (
            _normalized_instruction(occurrence.attributes.get("opcode"), occurrence.attributes.get("operands"))
            != signature
        ):
            continue
        if len(expected_neighborhood) > 1 and pcode_neighborhoods.get(occurrence.record_id) != expected_neighborhood:
            continue
        for edge, virtual, map_edge, allocator in legacy_allocator_chains_from_occurrence(
            graph,
            occurrence.record_id,
            edge_kind,
            raw_position,
        ):
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
        candidates = () if virtual_id is None else legacy_allocator_from_virtual(graph, virtual_id)
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


_OWNER_STATUS_PRIORITY = (
    OwnerResolutionStatus.CONTRADICTORY,
    OwnerResolutionStatus.INCOMPLETE,
    OwnerResolutionStatus.AMBIGUOUS,
    OwnerResolutionStatus.MISSING,
)
_OWNER_ABSTENTION_REASONS = {
    OwnerResolutionStatus.CONTRADICTORY: "backend-owner-contradictory",
    OwnerResolutionStatus.INCOMPLETE: "backend-owner-path-incomplete",
    OwnerResolutionStatus.AMBIGUOUS: "backend-owner-ambiguous",
    OwnerResolutionStatus.MISSING: "backend-owner-missing",
}


def _certificate_semantics(
    certificate: EvidenceNode,
    role: OwnerRoleKey,
) -> OwnerSemanticState | None:
    role_value = certificate.attributes.get("role")
    state_value = certificate.attributes.get("semantic_state")
    if not isinstance(role_value, Mapping) or not isinstance(state_value, Mapping):
        return None
    try:
        parsed_role = OwnerRoleKey(**role_value)
        state = OwnerSemanticState(**state_value)
        parsed_role.validate()
        state.validate()
    except (TypeError, ValueError):
        return None
    return state if parsed_role == role else None


def _trusted_certificate(
    result: OwnerCertificateResult,
    role: OwnerRoleKey,
    record_id: str,
) -> EvidenceNode | None:
    certificate = result.certificate(record_id)
    if certificate is None or certificate.kind != "owner-proof-certificate":
        return None
    if certificate.provenance.parser != "causal-owner-certificate.v1":
        return None
    if _certificate_semantics(certificate, role) is None:
        return None
    return certificate


def _stored_certificate(
    graph: FrontierGraph,
    result: OwnerCertificateResult,
    role: OwnerRoleKey,
    record_id: str,
) -> EvidenceNode | None:
    certificate = _trusted_certificate(result, role, record_id)
    if certificate is None:
        return None
    stored = graph.store.get_node(record_id)
    if stored is None or canonical_record_bytes(stored) != canonical_record_bytes(certificate):
        return None
    return certificate


def _certificate_bound_node(
    graph: FrontierGraph,
    result: OwnerCertificateResult,
    certificate: EvidenceNode,
    record_id: str,
    kind: str,
) -> EvidenceNode | None:
    bound = result.certificate_support_node(certificate.record_id, record_id)
    stored = graph.store.get_node(record_id)
    if bound is None or stored is None or bound.kind != kind or stored.kind != kind:
        return None
    if canonical_record_bytes(bound) != canonical_record_bytes(stored):
        return None
    return bound


def _effective_owner_resolution(
    graph: FrontierGraph,
    result: OwnerCertificateResult,
    role: OwnerRoleKey,
    resolution: OwnerRoleResolution,
) -> tuple[OwnerResolutionStatus, tuple[EvidenceNode, ...]]:
    certificates = tuple(
        certificate
        for record_id in resolution.certificate_record_ids
        if (certificate := _stored_certificate(graph, result, role, record_id)) is not None
    )
    status = resolution.status
    if status is OwnerResolutionStatus.UNIQUE and (
        len(resolution.certificate_record_ids) != 1 or len(certificates) != 1
    ):
        status = OwnerResolutionStatus.INCOMPLETE
    return status, certificates


def _rejection_summary(
    side: str,
    rejection: OwnerCertificateRejection,
) -> Mapping[str, object]:
    return {
        "kind": "rejection",
        "side": side,
        "certificate_record_id": None,
        "role": None if rejection.role is None else rejection.role.as_json(),
        "state": None,
        "confidence": Confidence.HEURISTIC.value,
        "provenance_record_ids": (),
        "rejection_id": rejection.rejection_id,
        "reason": rejection.reason,
        "candidate_record_ids": tuple(sorted(rejection.candidate_record_ids)),
        "support_record_ids": tuple(sorted(rejection.raw_support_record_ids)),
    }


def _certificate_multiplicity(
    result: OwnerCertificateResult,
    role: OwnerRoleKey,
    certificate: EvidenceNode,
) -> int:
    state = _certificate_semantics(certificate, role)
    if state is None:
        return 1
    provenance_ids = tuple(sorted(certificate.provenance.input_record_ids))
    return next(
        (
            group.multiplicity
            for group in result._canonical_groups
            if group.role == role
            and group.semantic_state == state
            and provenance_ids in tuple(tuple(sorted(record_ids)) for record_ids in group.provenance_record_ids)
        ),
        1,
    )


def _owner_alternatives(
    side: str,
    role: OwnerRoleKey,
    result: OwnerCertificateResult,
    resolution: OwnerRoleResolution,
    certificates: tuple[EvidenceNode, ...],
) -> tuple[Mapping[str, object], ...]:
    raw: list[Mapping[str, object]] = []
    certificates_by_id = {certificate.record_id: certificate for certificate in certificates}
    for record_id in resolution.certificate_record_ids:
        certificate = _trusted_certificate(result, role, record_id)
        if certificate is not None:
            certificates_by_id.setdefault(record_id, certificate)
    for certificate in certificates_by_id.values():
        state = _certificate_semantics(certificate, role)
        assert state is not None
        summary = {
            "kind": "certificate",
            "side": side,
            "certificate_record_id": certificate.record_id,
            "role": role.as_json(),
            "state": state.as_json(),
            "confidence": certificate.confidence.value,
            "provenance_record_ids": tuple(sorted(certificate.provenance.input_record_ids)),
            "rejection_id": None,
            "reason": None,
            "candidate_record_ids": (),
            "support_record_ids": (),
        }
        raw.extend((summary,) * _certificate_multiplicity(result, role, certificate))
    raw.extend(_rejection_summary(side, rejection) for rejection in (*resolution.rejections, *result.global_rejections))
    grouped: dict[bytes, tuple[Mapping[str, object], int]] = {}
    for summary in raw:
        key = canonical_bytes(summary)
        prior = grouped.get(key)
        grouped[key] = (summary, 1 if prior is None else prior[1] + 1)
    return tuple({**summary, "multiplicity": multiplicity} for _key, (summary, multiplicity) in sorted(grouped.items()))


def _owner_correspondence(
    analysis_id: str,
    role: OwnerRoleKey,
    left: EvidenceNode,
    right: EvidenceNode,
    ordinal: int,
) -> ComparisonRecord:
    inputs = (left, right)
    confidence = min_confidence(*(certificate.confidence for certificate in inputs))
    role_digest = hashlib.sha256(canonical_bytes(role.as_json())).hexdigest()
    return ComparisonRecord.create(
        analysis_id=analysis_id,
        relation_kind="backend-owner-corresponds-to",
        left_compile_id=left.compile_id,
        left_record_id=left.record_id,
        right_compile_id=right.compile_id,
        right_record_id=right.record_id,
        producer_confidence=confidence,
        adapter_confidence=confidence,
        provenance=Provenance(
            artifact_sha256=analysis_id,
            parser="causal-backend-owner-alignment.v2",
            raw_start=None,
            raw_end=None,
            derivation_rule=f"certified-owner-role:{role_digest}",
            input_record_ids=tuple(certificate.record_id for certificate in inputs),
        ),
        input_confidences=tuple(certificate.confidence for certificate in inputs),
        occurrence_ordinal=ordinal,
        attributes={"role": role.as_json()},
    )


def _owner_abstention(
    analysis_id: str,
    role: OwnerRoleKey,
    left_graph: FrontierGraph,
    right_graph: FrontierGraph,
    left_resolution: OwnerRoleResolution,
    right_resolution: OwnerRoleResolution,
    left_status: OwnerResolutionStatus,
    right_status: OwnerResolutionStatus,
    left_certificates: tuple[EvidenceNode, ...],
    right_certificates: tuple[EvidenceNode, ...],
    ordinal: int,
) -> ComparisonRecord:
    status = next(item for item in _OWNER_STATUS_PRIORITY if item in {left_status, right_status})
    alternatives = tuple(
        sorted(
            (
                *_owner_alternatives(
                    "left", role, left_graph.backend.owner_certificates, left_resolution, left_certificates
                ),
                *_owner_alternatives(
                    "right", role, right_graph.backend.owner_certificates, right_resolution, right_certificates
                ),
            ),
            key=canonical_bytes,
        )
    )
    alternatives_digest = hashlib.sha256(
        canonical_bytes({"role": role.as_json(), "alternatives": alternatives})
    ).hexdigest()
    inputs_by_id = {certificate.record_id: certificate for certificate in (*left_certificates, *right_certificates)}
    inputs = tuple(inputs_by_id[record_id] for record_id in sorted(inputs_by_id))
    left_endpoint = left_certificates[0] if len(left_certificates) == 1 else None
    right_endpoint = right_certificates[0] if len(right_certificates) == 1 else None
    return ComparisonRecord.create(
        analysis_id=analysis_id,
        relation_kind="backend-owner-abstained",
        left_compile_id=_compile_id(left_graph),
        left_record_id=None if left_endpoint is None else left_endpoint.record_id,
        right_compile_id=_compile_id(right_graph),
        right_record_id=None if right_endpoint is None else right_endpoint.record_id,
        producer_confidence=Confidence.HEURISTIC,
        adapter_confidence=Confidence.HEURISTIC,
        provenance=Provenance(
            artifact_sha256=analysis_id,
            parser="causal-backend-owner-alignment.v2",
            raw_start=None,
            raw_end=None,
            derivation_rule=f"certified-owner-abstention:{alternatives_digest}",
            input_record_ids=tuple(record.record_id for record in inputs),
        ),
        input_confidences=tuple(record.confidence for record in inputs),
        occurrence_ordinal=ordinal,
        attributes={
            "reason": _OWNER_ABSTENTION_REASONS[status],
            "role": role.as_json(),
            "left_status": left_status.value,
            "right_status": right_status.value,
            "certificate_record_ids": {
                "left": tuple(sorted(left_resolution.certificate_record_ids)),
                "right": tuple(sorted(right_resolution.certificate_record_ids)),
            },
            "rejections": {
                "left": tuple(
                    _rejection_summary("left", item)
                    for item in sorted(
                        (*left_resolution.rejections, *left_graph.backend.owner_certificates.global_rejections),
                        key=lambda item: item.rejection_id,
                    )
                ),
                "right": tuple(
                    _rejection_summary("right", item)
                    for item in sorted(
                        (*right_resolution.rejections, *right_graph.backend.owner_certificates.global_rejections),
                        key=lambda item: item.rejection_id,
                    )
                ),
            },
            "alternatives": alternatives,
        },
    )


def _trusted_owner_roles(result: OwnerCertificateResult) -> tuple[OwnerRoleKey, ...]:
    if not result.is_trusted:
        return ()
    roles = []
    for resolution in result.role_resolutions:
        role = resolution.role
        if type(role) is not OwnerRoleKey:
            continue
        try:
            role.validate()
        except (TypeError, ValueError):
            continue
        roles.append(role)
    return tuple(sorted(set(roles)))


def _owner_resolution(
    result: OwnerCertificateResult,
    role: OwnerRoleKey,
) -> OwnerRoleResolution:
    if not result.is_trusted:
        return OwnerRoleResolution(
            role,
            OwnerResolutionStatus.INCOMPLETE,
            (),
            (),
        )
    return result.resolution_for(role)


def build_role_comparisons(alignment: AnchorAlignment, graphs: Iterable[FrontierGraph]) -> tuple[ComparisonRecord, ...]:
    """Return generic correspondences plus certificate-only owner resolution."""

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
    left_graph, right_graph = tuple(sorted(graph_pair, key=_label))
    left_result = left_graph.backend.owner_certificates
    right_result = right_graph.backend.owner_certificates
    roles = tuple(
        sorted(
            {
                *_trusted_owner_roles(left_result),
                *_trusted_owner_roles(right_result),
            }
        )
    )
    for ordinal, role in enumerate(roles):
        left_resolution = _owner_resolution(left_result, role)
        right_resolution = _owner_resolution(right_result, role)
        left_status, left_certificates = _effective_owner_resolution(left_graph, left_result, role, left_resolution)
        right_status, right_certificates = _effective_owner_resolution(
            right_graph, right_result, role, right_resolution
        )
        if left_status is right_status is OwnerResolutionStatus.UNIQUE:
            comparisons.append(
                _owner_correspondence(
                    alignment.analysis_id,
                    role,
                    left_certificates[0],
                    right_certificates[0],
                    ordinal,
                )
            )
        else:
            comparisons.append(
                _owner_abstention(
                    alignment.analysis_id,
                    role,
                    left_graph,
                    right_graph,
                    left_resolution,
                    right_resolution,
                    left_status,
                    right_status,
                    left_certificates,
                    right_certificates,
                    ordinal,
                )
            )
    return tuple(comparisons)


__all__ = [
    "AbstentionReason",
    "AnchorAlignment",
    "EffectAbstention",
    "OperandRole",
    "RolePair",
    "align_anchor",
    "build_role_comparisons",
]
