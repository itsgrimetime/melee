"""Strict, storage-neutral inference over normalized causal evidence."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .alignment import owner_alignment_record_is_authoritative
from .canonical import canonical_bytes, stable_id
from .differ import owner_delta_record_is_authoritative
from .effects import DerivedEffects, EffectPair
from .graph import FrontierGraph
from .legacy_ownership import legacy_simple_paths_with_truncation
from .models import AdapterResult, ComparisonRecord, Confidence, EvidenceEdge, EvidenceNode
from .owner_certificate import OwnerCertificateResult, OwnerRoleKey, OwnerSemanticState
from .store import EvidenceQuery, canonical_record_bytes

_OWNER_KINDS = frozenset({"compiler-object", "source-expression", "objobject", "inline-scope"})
_DELTA_RELATIONS = frozenset(
    {
        "node-added",
        "node-removed",
        "node-changed",
        "edge-added",
        "edge-removed",
        "edge-changed",
    }
)
_PROOF_CONFIDENCES = frozenset({Confidence.OBSERVED, Confidence.DERIVED_UNIQUE})
_DIAGNOSTIC_ONLY_PARSERS = frozenset({"mwcc-debug-pcdump.v1"})
_OWNER_CORRESPONDENCE_PARSER = "causal-backend-owner-alignment.v2"
_OWNER_DELTA_PARSER = "causal-frontier-differ.v1"
_BACKEND_OWNER_AMBIGUOUS = "backend-owner-ambiguous"

_GATE_1 = "gate-1-anchor-identity"
_GATE_2 = "gate-2-backend-role-identity"
_GATE_3 = "gate-3-shared-owner"
_GATE_4 = "gate-4-allocator-delta"
_GATE_5 = "gate-5-stack-delta"
_GATE_6 = "gate-6-unique-owner-chain"
_GATE_7 = "gate-7-proof-capable-path"
_GATE_8 = "gate-8-evidence-integrity"
_GATE_9 = "gate-9-source-object-binding"
_SOURCE_OBJECT_BINDING_MISSING = "source-object-binding-missing"

_OPERATIONAL_SCOPE = (
    "Operational compiler-evidence scope: verdicts are limited to the compared "
    "target-centered graphs and do not claim unrestricted program causality."
)
_READ_ONLY_COMMANDS = (
    "melee-agent debug inspect lifetime-pressure --help",
    "melee-agent debug inspect stack-homes --help",
)


class VerdictStatus(StrEnum):
    CAUSES = "causes"
    CANDIDATE_CAUSE = "candidate-cause"
    NO_CAUSAL_DIFFERENCE = "no-causal-difference"
    ABSTAIN = "abstain"


class AnalysisStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class AppliedRule:
    rule_id: str
    input_record_ids: tuple[str, ...]
    output_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CausalVerdict:
    verdict_id: str
    status: VerdictStatus
    pair_id: str
    cause: EvidenceNode | None
    proof_paths: tuple[tuple[str, ...], ...]
    rejected_alternatives: tuple[str, ...]
    failed_gates: tuple[str, ...]
    allocator_delta: Mapping[str, object]
    stack_delta: Mapping[str, object]
    recommendation: str
    follow_up_commands: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allocator_delta", MappingProxyType(dict(self.allocator_delta)))
        object.__setattr__(self, "stack_delta", MappingProxyType(dict(self.stack_delta)))


@dataclass(frozen=True, slots=True)
class CausalDiffReport:
    schema_version: Literal["causal-diff-report.v1"]
    analysis_id: str
    analysis_status: AnalysisStatus
    function: str
    effects: DerivedEffects
    verdicts: tuple[CausalVerdict, ...]
    comparisons: tuple[ComparisonRecord, ...]
    applied_rules: tuple[AppliedRule, ...]
    missing_evidence: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return report_to_canonical_dict(self)


@dataclass(frozen=True, slots=True)
class _OwnerAlternative:
    comparison: ComparisonRecord
    node: EvidenceNode
    paths: tuple[tuple[str, ...], ...]
    proof_capable: bool


@dataclass(frozen=True, slots=True)
class _OwnerEnumeration:
    alternatives: tuple[_OwnerAlternative, ...]
    rejected: tuple[str, ...]
    incomplete: bool
    truncated: bool


@dataclass(frozen=True, slots=True)
class _PathEnumeration:
    paths: tuple[tuple[str, ...], ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class _SourceBindingEnumeration:
    records: tuple[EvidenceEdge, ...]
    paths: tuple[tuple[str, ...], ...]
    complete: bool


class _ScopedEvidenceQuery:
    """Read-only union restricted to the two frontier compile scopes."""

    def __init__(
        self,
        queries: Iterable[EvidenceQuery],
        compile_ids: frozenset[str],
    ) -> None:
        self._queries = tuple({id(query): query for query in queries}.values())
        self._compile_ids = compile_ids

    def get_node(self, record_id: str) -> EvidenceNode | None:
        for query in self._queries:
            node = query.get_node(record_id)
            if node is not None and node.compile_id in self._compile_ids:
                return node
        return None

    def get_edge(self, record_id: str) -> EvidenceEdge | None:
        for query in self._queries:
            edge = query.get_edge(record_id)
            if edge is not None and edge.compile_id in self._compile_ids:
                return edge
        return None

    def neighbors(
        self,
        record_id: str,
        edge_kinds: frozenset[str] | None = None,
        direction: Literal["in", "out", "both"] = "both",
    ) -> tuple[EvidenceEdge, ...]:
        records = {
            edge.record_id: edge
            for query in self._queries
            for edge in query.neighbors(record_id, edge_kinds, direction)
            if edge.compile_id in self._compile_ids
            and self.get_node(edge.source_id) is not None
            and self.get_node(edge.target_id) is not None
        }
        return tuple(
            sorted(
                records.values(),
                key=lambda edge: (
                    edge.kind,
                    edge.source_id,
                    edge.target_id,
                    edge.record_id,
                ),
            )
        )

    def find_nodes(
        self,
        compile_id: str,
        node_kind: str | None = None,
        role_key: str | None = None,
    ) -> tuple[EvidenceNode, ...]:
        if compile_id not in self._compile_ids:
            return ()
        records = {
            node.record_id: node
            for query in self._queries
            for node in query.find_nodes(compile_id, node_kind, role_key)
        }
        return tuple(
            sorted(
                records.values(),
                key=lambda node: (node.kind, node.role_key or "", node.record_id),
            )
        )

    def find_edges(
        self,
        compile_id: str,
        edge_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[EvidenceEdge, ...]:
        if compile_id not in self._compile_ids:
            return ()
        records = {
            edge.record_id: edge
            for query in self._queries
            for edge in query.find_edges(compile_id, edge_kind, endpoint)
            if self.get_node(edge.source_id) is not None and self.get_node(edge.target_id) is not None
        }
        return tuple(
            sorted(
                records.values(),
                key=lambda edge: (
                    edge.kind,
                    edge.source_id,
                    edge.target_id,
                    edge.record_id,
                ),
            )
        )

    def find_comparisons(
        self,
        analysis_id: str,
        relation_kind: str | None = None,
        endpoint: str | None = None,
    ) -> tuple[ComparisonRecord, ...]:
        records = {
            comparison.record_id: comparison
            for query in self._queries
            for comparison in query.find_comparisons(analysis_id, relation_kind, endpoint)
            if comparison.left_compile_id in self._compile_ids and comparison.right_compile_id in self._compile_ids
        }
        return tuple(sorted(records.values(), key=lambda item: item.record_id))

    def subgraph(
        self,
        roots: Iterable[str],
        edge_kinds: frozenset[str],
        max_depth: int,
    ) -> AdapterResult:
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        included = {record_id for record_id in roots if self.get_node(record_id)}
        edge_ids: set[str] = set()
        frontier = sorted(included)
        for _depth in range(max_depth):
            next_frontier: set[str] = set()
            for record_id in frontier:
                for edge in self.neighbors(record_id, edge_kinds):
                    edge_ids.add(edge.record_id)
                    other = edge.target_id if edge.source_id == record_id else edge.source_id
                    if other not in included:
                        included.add(other)
                        next_frontier.add(other)
            frontier = sorted(next_frontier)
            if not frontier:
                break
        return AdapterResult(
            nodes=tuple(node for record_id in sorted(included) if (node := self.get_node(record_id)) is not None),
            edges=tuple(edge for record_id in sorted(edge_ids) if (edge := self.get_edge(record_id)) is not None),
        )


def _record_for_id(query: EvidenceQuery, record_id: str) -> EvidenceNode | EvidenceEdge | None:
    return query.get_node(record_id) or query.get_edge(record_id)


def _legacy_simple_path_search(
    query: EvidenceQuery,
    source_id: str,
    target_id: str,
    max_depth: int,
) -> _PathEnumeration:
    """Enumerate legacy-only paths while retaining the depth truncation signal."""

    paths, truncated = legacy_simple_paths_with_truncation(query, source_id, target_id, max_depth)
    return _PathEnumeration(paths, truncated)


def _record_is_proof_capable(record: EvidenceNode | EvidenceEdge | ComparisonRecord) -> bool:
    return record.confidence in _PROOF_CONFIDENCES and record.provenance.parser not in _DIAGNOSTIC_ONLY_PARSERS


def _path_is_proof_capable(query: EvidenceQuery, path: tuple[str, ...]) -> bool:
    records = tuple(_record_for_id(query, record_id) for record_id in path)
    return all(record is not None and _record_is_proof_capable(record) for record in records)


def _truthy_attribute(record: object, keys: frozenset[str]) -> bool:
    attributes = getattr(record, "attributes", {})
    return isinstance(attributes, Mapping) and any(attributes.get(key) is True for key in keys)


def _false_attribute(record: object, keys: frozenset[str]) -> bool:
    attributes = getattr(record, "attributes", {})
    return isinstance(attributes, Mapping) and any(attributes.get(key) is False for key in keys)


def _evidence_integrity_failure(records: Iterable[object]) -> bool:
    truthy_failures = frozenset(
        {
            "traversal_truncated",
            "truncated",
            "path_incomplete",
            "missing_required_evidence",
            "contradiction",
            "contradictory",
            "ownership_contradiction",
        }
    )
    false_failures = frozenset(
        {
            "alternatives_enumerable",
            "artifact_valid",
            "digest_valid",
            "environment_valid",
            "compile_environment_valid",
            "compatible",
        }
    )
    return any(
        _truthy_attribute(record, truthy_failures) or _false_attribute(record, false_failures) for record in records
    )


def _owner_role(value: object) -> OwnerRoleKey | None:
    if not isinstance(value, Mapping) or frozenset(value) != {
        "operand_key",
        "register_class",
        "semantic_stack_role",
        "type_size",
        "frame_area",
    }:
        return None
    try:
        role = OwnerRoleKey(**value)
        role.validate()
    except (TypeError, ValueError):
        return None
    return role


def _owner_state(value: object) -> OwnerSemanticState | None:
    if not isinstance(value, Mapping) or frozenset(value) != {
        "assigned_physical_register",
        "stack_offset",
        "stack_size",
    }:
        return None
    try:
        state = OwnerSemanticState(**value)
        state.validate()
    except (TypeError, ValueError):
        return None
    return state


def _record_id_tuple(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, tuple) or not all(isinstance(item, str) and item for item in value):
        return None
    return value


def _bilateral_node_deltas(
    comparisons: tuple[ComparisonRecord, ...],
    record_ids: frozenset[str],
) -> tuple[ComparisonRecord, ...]:
    return tuple(
        comparison
        for comparison in comparisons
        if comparison.relation_kind == "node-changed"
        and comparison.left_record_id is not None
        and comparison.right_record_id is not None
        and frozenset({comparison.left_record_id, comparison.right_record_id}) == record_ids
    )


def _bilateral_source_object_records(
    alternatives: tuple[_OwnerAlternative, ...],
    query: EvidenceQuery,
) -> _SourceBindingEnumeration:
    owners: dict[str, EvidenceNode] = {}
    for alternative in alternatives:
        comparison = alternative.comparison
        endpoint_ids = (comparison.left_record_id, comparison.right_record_id)
        endpoints = tuple(query.get_node(record_id) if record_id is not None else None for record_id in endpoint_ids)
        if any(node is None or node.kind != "compiler-object" for node in endpoints):
            return _SourceBindingEnumeration((), (), complete=False)
        for node in endpoints:
            assert node is not None
            owners[node.record_id] = node

    records: list[EvidenceEdge] = []
    paths: list[tuple[str, ...]] = []
    for owner in owners.values():
        candidates: list[tuple[EvidenceEdge, EvidenceNode]] = []
        for edge in query.find_edges(
            owner.compile_id,
            "object-to-source",
            endpoint=owner.record_id,
        ):
            if edge.source_id != owner.record_id:
                continue
            source = query.get_node(edge.target_id)
            if (
                source is None
                or source.kind != "source-expression"
                or not _record_is_proof_capable(edge)
                or not _record_is_proof_capable(owner)
                or not _record_is_proof_capable(source)
                or not {owner.record_id, source.record_id}.issubset(edge.provenance.input_record_ids)
            ):
                continue
            candidates.append((edge, source))
        if len(candidates) != 1:
            return _SourceBindingEnumeration((), (), complete=False)
        edge, source = candidates[0]
        records.append(edge)
        paths.append((owner.record_id, edge.record_id, source.record_id))
    return _SourceBindingEnumeration(
        records=tuple(sorted(records, key=lambda edge: edge.record_id)),
        paths=tuple(sorted(paths)),
        complete=bool(owners),
    )


def _stack_nodes_by_compile(pair: EffectPair, query: EvidenceQuery) -> Mapping[str, EvidenceNode]:
    expected_compile_ids = {
        pair.allocator.role_correspondence.left.compile_id,
        pair.allocator.role_correspondence.right.compile_id,
    }
    candidates: dict[str, list[EvidenceNode]] = {}
    for record_id in pair.stack.owner_record_ids:
        node = query.get_node(record_id)
        if node is not None and node.kind == "stack-object" and node.compile_id in expected_compile_ids:
            candidates.setdefault(node.compile_id, []).append(node)
    return MappingProxyType({compile_id: nodes[0] for compile_id, nodes in candidates.items() if len(nodes) == 1})


def _owner_alternatives(
    pair: EffectPair,
    query: EvidenceQuery,
    comparisons: tuple[ComparisonRecord, ...],
    evidence_depth: int,
) -> _OwnerEnumeration:
    allocator_by_compile = {
        pair.allocator.role_correspondence.left.compile_id: pair.allocator.role_correspondence.left,
        pair.allocator.role_correspondence.right.compile_id: pair.allocator.role_correspondence.right,
    }
    expected_compile_ids = frozenset(allocator_by_compile)
    stack_by_compile = _stack_nodes_by_compile(pair, query)

    complete: list[_OwnerAlternative] = []
    rejected: list[str] = []
    incomplete = False
    truncated = False
    for comparison in comparisons:
        if comparison.relation_kind not in _DELTA_RELATIONS:
            continue
        endpoints = tuple(
            node
            for record_id in (
                comparison.left_record_id,
                comparison.right_record_id,
            )
            if record_id is not None and (node := query.get_node(record_id)) is not None and node.kind in _OWNER_KINDS
        )
        if not endpoints:
            continue
        if (
            comparison.relation_kind != "node-changed"
            or comparison.left_record_id is None
            or comparison.right_record_id is None
            or {node.compile_id for node in endpoints} != expected_compile_ids
            or len(endpoints) != 2
        ):
            incomplete = True
            rejected.append(comparison.record_id)
            continue
        endpoint_alternatives: list[_OwnerAlternative] = []
        for owner in endpoints:
            allocator = allocator_by_compile.get(owner.compile_id)
            stack_target = stack_by_compile.get(owner.compile_id)
            if allocator is None or stack_target is None:
                continue
            allocator_search = _legacy_simple_path_search(
                query,
                owner.record_id,
                allocator.record_id,
                evidence_depth,
            )
            stack_search = _legacy_simple_path_search(
                query,
                owner.record_id,
                stack_target.record_id,
                evidence_depth,
            )
            truncated |= allocator_search.truncated or stack_search.truncated
            if not allocator_search.paths or not stack_search.paths:
                continue
            all_paths = tuple(
                sorted(
                    (*allocator_search.paths, *stack_search.paths),
                    key=lambda path: (len(path), path),
                )
            )
            endpoint_alternatives.append(
                _OwnerAlternative(
                    comparison=comparison,
                    node=owner,
                    paths=all_paths,
                    proof_capable=(
                        _record_is_proof_capable(comparison)
                        and all(_path_is_proof_capable(query, path) for path in all_paths)
                    ),
                )
            )
        if len(endpoint_alternatives) == 2:
            preferred_compile = next(
                (
                    node.compile_id
                    for label, node in (
                        (
                            pair.allocator.role_correspondence.left_label,
                            pair.allocator.role_correspondence.left,
                        ),
                        (
                            pair.allocator.role_correspondence.right_label,
                            pair.allocator.role_correspondence.right,
                        ),
                    )
                    if label == pair.allocator_exact_stack_mismatch_label
                ),
                "",
            )
            selected = min(
                endpoint_alternatives,
                key=lambda item: (
                    item.node.compile_id != preferred_compile,
                    item.node.record_id,
                ),
            )
            complete.append(
                _OwnerAlternative(
                    comparison=comparison,
                    node=selected.node,
                    paths=tuple(
                        sorted(
                            {path for alternative in endpoint_alternatives for path in alternative.paths},
                            key=lambda path: (len(path), path),
                        )
                    ),
                    proof_capable=all(alternative.proof_capable for alternative in endpoint_alternatives),
                )
            )
        elif endpoint_alternatives:
            incomplete = True
            rejected.append(comparison.record_id)
        else:
            rejected.append(comparison.record_id)
    return _OwnerEnumeration(
        alternatives=tuple(complete),
        rejected=tuple(
            sorted(
                {
                    *rejected,
                    *((f"traversal-truncated:evidence-depth={evidence_depth}",) if truncated else ()),
                }
            )
        ),
        incomplete=incomplete,
        truncated=truncated,
    )


def _shortest_paths(
    alternatives: tuple[_OwnerAlternative, ...],
    role_comparison_id: str,
) -> tuple[tuple[str, ...], ...]:
    selected: list[tuple[str, ...]] = []
    for alternative in alternatives:
        endpoints: dict[str, list[tuple[str, ...]]] = {}
        for path in alternative.paths:
            endpoints.setdefault(path[-1], []).append(path)
        selected.extend(
            (
                alternative.comparison.record_id,
                role_comparison_id,
                *min(paths, key=lambda path: (len(path), path)),
            )
            for _endpoint, paths in sorted(endpoints.items())
        )
    return tuple(sorted(set(selected), key=lambda path: (len(path), path)))


def _allocator_delta(pair: EffectPair) -> Mapping[str, object]:
    effect = pair.allocator
    return {
        "effect_id": effect.effect_id,
        "operand_key": effect.operand_key,
        "expected_phys": effect.expected_phys,
        "direction": effect.direction,
        "first_label": effect.first_label,
        "first_phys": effect.first_phys,
        "second_label": effect.second_label,
        "second_phys": effect.second_phys,
    }


def _stack_delta(pair: EffectPair) -> Mapping[str, object]:
    effect = pair.stack
    return {
        "effect_id": effect.effect_id,
        "role_key": effect.role_key,
        "expected_offset": effect.expected_offset,
        "direction": effect.direction,
        "first_label": effect.first_label,
        "first_offset": effect.first_offset,
        "second_label": effect.second_label,
        "second_offset": effect.second_offset,
    }


def _verdict(
    pair: EffectPair,
    *,
    status: VerdictStatus,
    cause: EvidenceNode | None,
    proof_paths: tuple[tuple[str, ...], ...],
    rejected_alternatives: tuple[str, ...],
    failed_gates: tuple[str, ...],
) -> CausalVerdict:
    if status is VerdictStatus.CAUSES:
        recommendation = (
            f"{_OPERATIONAL_SCOPE} The reported owner mediates both queried effects. "
            "Preserve the allocator dependency while testing a shorter stack "
            "materialization interval."
        )
    elif status is VerdictStatus.CANDIDATE_CAUSE:
        recommendation = (
            f"{_OPERATIONAL_SCOPE} Validate the finite alternatives before changing "
            "the allocator dependency or stack materialization interval."
        )
    elif status is VerdictStatus.NO_CAUSAL_DIFFERENCE:
        recommendation = (
            f"{_OPERATIONAL_SCOPE} No changed shared mediator was found for this "
            "allocator/stack effect pair within the complete target-centered graphs."
        )
    else:
        recommendation = (
            f"{_OPERATIONAL_SCOPE} Collect the named missing proof evidence before drawing a causal conclusion."
        )
    verdict_id = stable_id(
        pair.pair_id,
        "causal-verdict",
        {
            "status": status.value,
            "cause": None if cause is None else cause.record_id,
            "proof_paths": proof_paths,
            "rejected": rejected_alternatives,
            "failed_gates": failed_gates,
        },
    )
    return CausalVerdict(
        verdict_id=verdict_id,
        status=status,
        pair_id=pair.pair_id,
        cause=cause,
        proof_paths=proof_paths,
        rejected_alternatives=rejected_alternatives,
        failed_gates=failed_gates,
        allocator_delta=_allocator_delta(pair),
        stack_delta=_stack_delta(pair),
        recommendation=recommendation,
        follow_up_commands=_READ_ONLY_COMMANDS,
    )


def _certificate_proof_path(certificate: EvidenceNode) -> tuple[str, ...] | None:
    path_ids = _record_id_tuple(certificate.attributes.get("path_record_ids"))
    support_ids = _record_id_tuple(certificate.attributes.get("raw_support_record_ids"))
    if path_ids is None or support_ids is None or certificate.provenance.input_record_ids != (*path_ids, *support_ids):
        return None
    return (certificate.record_id, *path_ids, *support_ids)


def _matching_owner_abstention_records(
    records: tuple[ComparisonRecord, ...],
    role: OwnerRoleKey | None,
    owner_ids: frozenset[str],
) -> tuple[ComparisonRecord, ...]:
    return tuple(
        comparison
        for comparison in records
        if comparison.relation_kind == "backend-owner-abstained"
        and (
            (role is not None and _owner_role(comparison.attributes.get("role")) == role)
            or bool(
                owner_ids
                & {
                    record_id
                    for record_id in (
                        comparison.left_record_id,
                        comparison.right_record_id,
                    )
                    if record_id is not None
                }
            )
        )
    )


def _infer_certificate_pair(
    pair: EffectPair,
    query: EvidenceQuery,
    records: tuple[ComparisonRecord, ...],
    owner_certificate_results_by_compile: Mapping[str, OwnerCertificateResult],
) -> CausalVerdict:
    """Evaluate a certificate-mediated pair without traversing raw owner edges."""

    role_pair = pair.allocator.role_correspondence
    role_comparison = role_pair.comparison
    owner_ids = frozenset(pair.stack.owner_record_ids)
    identity_records = (
        query.get_node(role_pair.left.record_id),
        query.get_node(role_pair.right.record_id),
    )
    if not all(record is not None for record in identity_records):
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=(),
            failed_gates=(_GATE_1,),
        )

    expert_asserted = bool(
        role_pair.asserted_labels
        or role_comparison.attributes.get("expert_assertion")
        or role_comparison.attributes.get("verdict_cap") == VerdictStatus.CANDIDATE_CAUSE.value
    )
    role_registrations = tuple(
        comparison for comparison in records if comparison.record_id == role_comparison.record_id
    )
    role_registered = len(role_registrations) == 1 and canonical_record_bytes(
        role_registrations[0]
    ) == canonical_record_bytes(role_comparison)
    if not role_registered or expert_asserted or not _record_is_proof_capable(role_comparison):
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=(),
            failed_gates=(_GATE_2,),
        )

    expected_operand = pair.stack.owner_operand_key
    correspondences = tuple(
        comparison
        for comparison in records
        if comparison.relation_kind == "backend-owner-corresponds-to"
        and owner_alignment_record_is_authoritative(comparison)
        and comparison.provenance.parser == _OWNER_CORRESPONDENCE_PARSER
        and comparison.left_record_id is not None
        and comparison.right_record_id is not None
        and frozenset((comparison.left_record_id, comparison.right_record_id)) == owner_ids
        and (comparison_role := _owner_role(comparison.attributes.get("role"))) is not None
        and comparison_role.operand_key == expected_operand
        and comparison_role.operand_key in pair.allocator.operand_keys
    )
    deltas = tuple(
        comparison
        for comparison in records
        if comparison.relation_kind == "backend-owner-state-changed"
        and owner_delta_record_is_authoritative(comparison)
        and comparison.provenance.parser == _OWNER_DELTA_PARSER
        and comparison.left_record_id is not None
        and comparison.right_record_id is not None
        and frozenset((comparison.left_record_id, comparison.right_record_id)) == owner_ids
        and (delta_role := _owner_role(comparison.attributes.get("role"))) is not None
        and delta_role.operand_key == expected_operand
        and delta_role.operand_key in pair.allocator.operand_keys
    )
    relations_complete = len(correspondences) == 1 and len(deltas) == 1
    role = _owner_role(correspondences[0].attributes.get("role")) if relations_complete else None
    stored_certificates = tuple(
        sorted(
            (certificate for record_id in owner_ids if (certificate := query.get_node(record_id)) is not None),
            key=lambda item: item.record_id,
        )
    )
    states = tuple(_owner_state(certificate.attributes.get("semantic_state")) for certificate in stored_certificates)

    failed: list[str] = []
    if len(states) != 2 or any(state is None for state in states) or states[0] == states[1]:
        failed.append(_GATE_3)
    if (
        len(states) != 2
        or any(state is None for state in states)
        or states[0].assigned_physical_register == states[1].assigned_physical_register
    ):
        failed.append(_GATE_4)
    if (
        len(states) != 2
        or any(state is None for state in states)
        or (states[0].stack_offset, states[0].stack_size) == (states[1].stack_offset, states[1].stack_size)
    ):
        failed.append(_GATE_5)
    if not relations_complete or len(owner_ids) != 2:
        failed.append(_GATE_6)

    trusted_certificates: list[EvidenceNode] = []
    proof_certificates: list[EvidenceNode] = []
    for stored in stored_certificates:
        result = owner_certificate_results_by_compile.get(stored.compile_id)
        trusted = None if result is None else result.certificate(stored.record_id)
        if trusted is not None:
            trusted_certificates.append(trusted)
            if canonical_record_bytes(stored) == canonical_record_bytes(trusted):
                proof_certificates.append(trusted)
    if len(trusted_certificates) != 2:
        failed.append(_GATE_7)

    proof_paths = (
        tuple(path for certificate in proof_certificates if (path := _certificate_proof_path(certificate)) is not None)
        if relations_complete and len(proof_certificates) == 2
        else ()
    )
    integrity_failure = (
        not relations_complete
        or len(stored_certificates) != 2
        or any(certificate.kind != "owner-proof-certificate" for certificate in stored_certificates)
        or (len(proof_certificates) == 2 and len(proof_paths) != 2)
        or role is None
        or role.semantic_stack_role != pair.stack.role_key
        or any(_owner_role(certificate.attributes.get("role")) != role for certificate in stored_certificates)
        or len(trusted_certificates) == 2
        and any(
            canonical_record_bytes(stored) != canonical_record_bytes(trusted)
            for stored, trusted in zip(
                stored_certificates, sorted(trusted_certificates, key=lambda item: item.record_id)
            )
        )
    )
    cited_records: list[object] = [
        role_comparison,
        *stored_certificates,
        *correspondences,
        *deltas,
    ]
    if len(correspondences) == 1 and len(deltas) == 1:
        correspondence = correspondences[0]
        delta = deltas[0]
        left_state = _owner_state(delta.attributes.get("left_semantic_state"))
        right_state = _owner_state(delta.attributes.get("right_semantic_state"))
        certificates_by_id = {certificate.record_id: certificate for certificate in stored_certificates}
        left = certificates_by_id.get(delta.left_record_id or "")
        right = certificates_by_id.get(delta.right_record_id or "")
        integrity_failure |= (
            frozenset(correspondence.attributes) != {"role"}
            or frozenset(delta.attributes) != {"role", "left_semantic_state", "right_semantic_state"}
            or correspondence.left_compile_id != delta.left_compile_id
            or correspondence.right_compile_id != delta.right_compile_id
            or correspondence.left_record_id != delta.left_record_id
            or correspondence.right_record_id != delta.right_record_id
            or left is None
            or right is None
            or left.compile_id != delta.left_compile_id
            or right.compile_id != delta.right_compile_id
            or _owner_role(delta.attributes.get("role")) != role
            or left_state != _owner_state(left.attributes.get("semantic_state"))
            or right_state != _owner_state(right.attributes.get("semantic_state"))
            or not {left.record_id, right.record_id}.issubset(correspondence.provenance.input_record_ids)
            or not {
                correspondence.record_id,
                left.record_id,
                right.record_id,
            }.issubset(delta.provenance.input_record_ids)
            or not _record_is_proof_capable(correspondence)
            or not _record_is_proof_capable(delta)
        )
    matching_abstentions = _matching_owner_abstention_records(records, role, owner_ids)
    certified_abstentions = tuple(
        item
        for item in matching_abstentions
        if item.provenance.parser == _OWNER_CORRESPONDENCE_PARSER and owner_alignment_record_is_authoritative(item)
    )
    forged_abstentions = tuple(item for item in matching_abstentions if item not in certified_abstentions)
    if matching_abstentions:
        cited_records.extend(matching_abstentions)
    if integrity_failure or certified_abstentions or forged_abstentions or _evidence_integrity_failure(cited_records):
        failed.append(_GATE_8)

    if failed:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=proof_paths,
            rejected_alternatives=tuple(
                sorted(f"backend-owner-abstained:{item.record_id}" for item in certified_abstentions)
            ),
            failed_gates=tuple(dict.fromkeys(failed)),
        )
    return _verdict(
        pair,
        status=VerdictStatus.ABSTAIN,
        cause=None,
        proof_paths=tuple(sorted(proof_paths)),
        rejected_alternatives=(),
        failed_gates=(_GATE_9,),
    )


def infer_pair(
    pair: EffectPair,
    query: EvidenceQuery,
    comparisons: Iterable[ComparisonRecord],
    *,
    evidence_depth: int = 4,
    owner_certificate_results_by_compile: Mapping[str, OwnerCertificateResult] | None = None,
) -> CausalVerdict:
    """Apply the normative strict-inference table to one eligible effect pair."""

    if not 1 <= evidence_depth <= 8:
        raise ValueError("evidence depth must be between 1 and 8")

    role = pair.allocator.role_correspondence
    role_comparison = role.comparison
    compile_ids = frozenset({role.left.compile_id, role.right.compile_id})
    query = _ScopedEvidenceQuery((query,), compile_ids)
    records = tuple(
        sorted(
            (
                comparison
                for comparison in comparisons
                if comparison.left_compile_id in compile_ids and comparison.right_compile_id in compile_ids
            ),
            key=lambda record: record.record_id,
        )
    )
    if pair.stack.owner_operand_key is not None:
        return _infer_certificate_pair(
            pair,
            query,
            records,
            owner_certificate_results_by_compile or {},
        )
    owner_ambiguities = tuple(
        comparison
        for comparison in records
        if comparison.relation_kind == _BACKEND_OWNER_AMBIGUOUS
        and (role_tuple := comparison.attributes.get("role_tuple"))
        and isinstance(role_tuple, (list, tuple))
        and role_tuple[0] in pair.allocator.operand_keys
    )
    allocator_ids = frozenset({role.left.record_id, role.right.record_id})
    stack_nodes_by_compile = _stack_nodes_by_compile(pair, query)
    stack_ids = frozenset(node.record_id for node in stack_nodes_by_compile.values())

    identity_records = (query.get_node(role.left.record_id), query.get_node(role.right.record_id))
    identity_complete = all(record is not None for record in identity_records)
    expert_asserted = bool(
        role.asserted_labels
        or role_comparison.attributes.get("expert_assertion")
        or role_comparison.attributes.get("verdict_cap") == VerdictStatus.CANDIDATE_CAUSE.value
    )
    role_proof_capable = _record_is_proof_capable(role_comparison)
    role_registered = any(comparison.record_id == role_comparison.record_id for comparison in records)
    allocator_deltas = _bilateral_node_deltas(records, allocator_ids)
    stack_deltas = _bilateral_node_deltas(records, stack_ids)
    allocator_delta_proven = all(comparison.confidence in _PROOF_CONFIDENCES for comparison in allocator_deltas)
    stack_delta_proven = all(comparison.confidence in _PROOF_CONFIDENCES for comparison in stack_deltas)

    owner_enumeration = _owner_alternatives(
        pair,
        query,
        records,
        evidence_depth,
    )
    alternatives = owner_enumeration.alternatives
    rejected = owner_enumeration.rejected
    source_bindings = (
        _bilateral_source_object_records(alternatives, query)
        if alternatives
        else _SourceBindingEnumeration((), (), complete=False)
    )
    comparison_endpoints = (
        _record_for_id(query, record_id)
        for comparison in records
        for record_id in (comparison.left_record_id, comparison.right_record_id)
        if record_id is not None
    )
    cited_records: list[object] = [
        *records,
        *(record for record in identity_records if record),
        *(record for record in comparison_endpoints if record is not None),
        *source_bindings.records,
    ]
    cited_records.extend(source for path in source_bindings.paths if (source := query.get_node(path[-1])) is not None)
    for alternative in alternatives:
        cited_records.extend(
            record
            for path in alternative.paths
            for record_id in path
            if (record := _record_for_id(query, record_id)) is not None
        )
    if _evidence_integrity_failure(cited_records):
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(_GATE_8,),
        )
    if owner_enumeration.truncated:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(_GATE_8,),
        )
    if not identity_complete:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(_GATE_1,),
        )
    if not role_registered:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(_GATE_2,),
        )
    if owner_ambiguities:
        ambiguity_rejections = tuple(
            sorted(
                {
                    *rejected,
                    *(f"backend-owner-ambiguous:{comparison.record_id}" for comparison in owner_ambiguities),
                    *(
                        f"alternative-owner:{alternative['alternative_id']}"
                        for comparison in owner_ambiguities
                        for alternative in comparison.attributes.get("alternatives", ())
                    ),
                }
            )
        )
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=ambiguity_rejections,
            failed_gates=(_GATE_3, _GATE_6),
        )
    failed_required = tuple(
        gate
        for present, gate in (
            (bool(allocator_deltas), _GATE_4),
            (
                len(stack_nodes_by_compile) == 2 and bool(stack_deltas),
                _GATE_5,
            ),
        )
        if not present
    )
    if failed_required:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=failed_required,
        )
    if alternatives and not source_bindings.complete:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(_GATE_9,),
        )
    if owner_enumeration.incomplete:
        return _verdict(
            pair,
            status=VerdictStatus.ABSTAIN,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(_GATE_3,),
        )
    if not alternatives:
        return _verdict(
            pair,
            status=VerdictStatus.NO_CAUSAL_DIFFERENCE,
            cause=None,
            proof_paths=(),
            rejected_alternatives=rejected,
            failed_gates=(),
        )

    proof_paths = tuple(
        sorted(
            {
                *_shortest_paths(alternatives, role_comparison.record_id),
                *(
                    (
                        alternative.comparison.record_id,
                        role_comparison.record_id,
                        *path,
                    )
                    for alternative in alternatives
                    for path in source_bindings.paths
                    if path[0]
                    in {
                        alternative.comparison.left_record_id,
                        alternative.comparison.right_record_id,
                    }
                ),
            },
            key=lambda path: (len(path), path),
        )
    )
    all_proof_capable = all(alternative.proof_capable for alternative in alternatives)
    if (
        len(alternatives) == 1
        and all_proof_capable
        and role_proof_capable
        and allocator_delta_proven
        and stack_delta_proven
        and not expert_asserted
    ):
        return _verdict(
            pair,
            status=VerdictStatus.CAUSES,
            cause=alternatives[0].node,
            proof_paths=proof_paths,
            rejected_alternatives=rejected,
            failed_gates=(),
        )
    failed_gates = tuple(
        gate
        for failed, gate in (
            (expert_asserted or not role_proof_capable, _GATE_2),
            (
                any(alternative.comparison.confidence not in _PROOF_CONFIDENCES for alternative in alternatives),
                _GATE_3,
            ),
            (not allocator_delta_proven, _GATE_4),
            (not stack_delta_proven, _GATE_5),
            (len(alternatives) > 1, _GATE_6),
            (not all_proof_capable, _GATE_7),
        )
        if failed
    )
    return _verdict(
        pair,
        status=VerdictStatus.CANDIDATE_CAUSE,
        cause=alternatives[0].node if len(alternatives) == 1 else None,
        proof_paths=proof_paths,
        rejected_alternatives=(
            *rejected,
            *(
                f"alternative-owner:{alternative.comparison.record_id}:{alternative.node.record_id}"
                for alternative in alternatives
                if len(alternatives) > 1
            ),
        ),
        failed_gates=failed_gates,
    )


def _analysis_status(verdicts: tuple[CausalVerdict, ...], effects: DerivedEffects) -> AnalysisStatus:
    evaluated = tuple(verdict for verdict in verdicts if verdict.status is not VerdictStatus.ABSTAIN)
    if not evaluated:
        return AnalysisStatus.ABSTAINED
    if effects.abstentions or len(evaluated) != len(verdicts):
        return AnalysisStatus.PARTIAL
    return AnalysisStatus.COMPLETE


def _analysis_id(
    effects: DerivedEffects,
    comparisons: tuple[ComparisonRecord, ...],
    fallback: str,
) -> str:
    analysis_ids = {comparison.analysis_id for comparison in comparisons}
    analysis_ids.update(pair.allocator.role_correspondence.comparison.analysis_id for pair in effects.pairs)
    if len(analysis_ids) > 1:
        raise ValueError("report inputs require exactly one analysis ID")
    return next(iter(analysis_ids), fallback)


def _no_eligible_pair_verdict(analysis_id: str, effects: DerivedEffects) -> CausalVerdict:
    allocator_effect_ids = tuple(sorted(effect.effect_id for effect in effects.allocator_effects))
    stack_effect_ids = tuple(sorted(effect.effect_id for effect in effects.stack_effects))
    pair_id = stable_id(
        analysis_id,
        "no-eligible-effect-pair",
        (allocator_effect_ids, stack_effect_ids),
    )
    verdict_id = stable_id(pair_id, "causal-verdict", VerdictStatus.NO_CAUSAL_DIFFERENCE.value)
    return CausalVerdict(
        verdict_id=verdict_id,
        status=VerdictStatus.NO_CAUSAL_DIFFERENCE,
        pair_id=pair_id,
        cause=None,
        proof_paths=(),
        rejected_alternatives=(),
        failed_gates=(),
        allocator_delta={
            "effect_id": stable_id(analysis_id, "allocator-effect-set", allocator_effect_ids),
            "effect_ids": allocator_effect_ids,
            "eligible_pair": False,
        },
        stack_delta={
            "effect_id": stable_id(analysis_id, "stack-effect-set", stack_effect_ids),
            "effect_ids": stack_effect_ids,
            "eligible_pair": False,
        },
        recommendation=(
            f"{_OPERATIONAL_SCOPE} No eligible allocator-improvement/stack-regression "
            "pair exists in the complete target-centered graphs."
        ),
        follow_up_commands=_READ_ONLY_COMMANDS,
    )


def build_report(
    graphs: Iterable[FrontierGraph],
    effects: DerivedEffects,
    comparisons: Iterable[ComparisonRecord],
    *,
    evidence_depth: int = 4,
) -> CausalDiffReport:
    """Infer every pair and aggregate a deterministic versioned report."""

    if not 1 <= evidence_depth <= 8:
        raise ValueError("evidence depth must be between 1 and 8")

    graph_pair = tuple(graphs)
    if len(graph_pair) != 2:
        raise ValueError("causal report requires exactly two frontier graphs")
    functions = {str(graph.bundle.manifest.function) for graph in graph_pair}
    if len(functions) != 1:
        raise ValueError("causal report frontiers must name one function")
    query = _ScopedEvidenceQuery(
        (graph.store for graph in graph_pair),
        frozenset(str(graph.bundle.compile_id) for graph in graph_pair),
    )
    comparison_records = tuple(sorted(comparisons, key=lambda record: record.record_id))
    fallback_analysis_id = stable_id(
        "causal-analysis",
        "inference-report-fallback",
        {
            "function": next(iter(functions)),
            "frontiers": tuple(
                sorted(
                    (
                        str(graph.bundle.label),
                        str(graph.bundle.compile_id),
                    )
                    for graph in graph_pair
                )
            ),
        },
    )
    analysis_id = _analysis_id(effects, comparison_records, fallback_analysis_id)
    owner_certificate_results_by_compile = {
        str(graph.bundle.compile_id): result
        for graph in graph_pair
        if (
            result := getattr(
                getattr(graph, "backend", None),
                "owner_certificates",
                None,
            )
        )
        is not None
    }
    inferred_verdicts = tuple(
        sorted(
            (
                infer_pair(
                    pair,
                    query,
                    comparison_records,
                    evidence_depth=evidence_depth,
                    owner_certificate_results_by_compile=owner_certificate_results_by_compile,
                )
                for pair in sorted(effects.pairs, key=lambda item: item.pair_id)
            ),
            key=lambda verdict: (verdict.pair_id, verdict.verdict_id),
        )
    )
    verdicts = (
        (_no_eligible_pair_verdict(analysis_id, effects),)
        if not inferred_verdicts and not effects.abstentions
        else inferred_verdicts
    )
    backend_missing = {
        reason
        for graph in graph_pair
        if (
            reason := getattr(
                getattr(graph, "backend", None),
                "owner_abstention_reason",
                None,
            )
        )
        is not None
    }
    missing_evidence = tuple(
        sorted(
            {f"{abstention.reason.value}:{abstention.operand_key}" for abstention in effects.abstentions}
            | {
                item
                for abstention in effects.abstentions
                for item in (
                    *abstention.missing_capability_ids,
                    *abstention.missing_record_ids,
                )
            }
            | (
                {_SOURCE_OBJECT_BINDING_MISSING}
                if any(_GATE_9 in verdict.failed_gates for verdict in verdicts)
                else set()
            )
            | backend_missing
            | (
                {_BACKEND_OWNER_AMBIGUOUS}
                if any(
                    any(
                        alternative.startswith("backend-owner-ambiguous:")
                        for alternative in verdict.rejected_alternatives
                    )
                    for verdict in verdicts
                )
                else set()
            )
        )
    )
    warnings = tuple(sorted({warning for graph in graph_pair for warning in graph.warnings}))
    comparison_ids = {comparison.record_id for comparison in comparison_records}
    applied_rules = tuple(
        AppliedRule(
            rule_id="dual-effect-shared-owner.v1",
            input_record_ids=tuple(
                sorted(
                    {record_id for path in verdict.proof_paths for record_id in path}
                    | comparison_ids
                    | {
                        str(verdict.allocator_delta["effect_id"]),
                        str(verdict.stack_delta["effect_id"]),
                    }
                )
            ),
            output_record_ids=(verdict.verdict_id,),
        )
        for verdict in verdicts
    )
    return CausalDiffReport(
        schema_version="causal-diff-report.v1",
        analysis_id=analysis_id,
        analysis_status=_analysis_status(verdicts, effects),
        function=next(iter(functions)),
        effects=effects,
        verdicts=verdicts,
        comparisons=comparison_records,
        applied_rules=applied_rules,
        missing_evidence=missing_evidence,
        warnings=warnings,
    )


def exit_code_for_report(report: CausalDiffReport) -> int:
    """Return the documented post-validation analysis exit code."""

    return 3 if report.analysis_status is AnalysisStatus.ABSTAINED else 0


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical_value(item) for item in value), key=canonical_bytes)
    return value


_UNORDERED_SEQUENCE_KEYS = frozenset(
    {
        "asserted_labels",
        "effect_ids",
        "failed_gates",
        "follow_up_commands",
        "input_record_ids",
        "missing_capability_ids",
        "missing_evidence",
        "missing_record_ids",
        "output_record_ids",
        "owner_record_ids",
        "rejected_alternatives",
        "warnings",
    }
)


def _sort_semantic_collections(value: object, field_name: str = "") -> object:
    """Sort schema-declared sets while preserving ordered sequence semantics."""

    if isinstance(value, dict):
        return {key: _sort_semantic_collections(item, key) for key, item in value.items()}
    if isinstance(value, list):
        if field_name == "proof_paths":
            # Path order is semantic; only the collection of whole paths is a set.
            paths = [list(path) for path in value]
            return sorted(paths)
        items = [_sort_semantic_collections(item) for item in value]
        if field_name in _UNORDERED_SEQUENCE_KEYS:
            return sorted(items, key=canonical_bytes)
        return items
    return value


def report_to_canonical_dict(report: CausalDiffReport) -> dict[str, object]:
    """Return the stable ``causal-diff-report.v1`` JSON object."""

    payload = _sort_semantic_collections(_canonical_value(report))
    assert isinstance(payload, dict)
    effects = payload["effects"]
    assert isinstance(effects, dict)
    effects["allocator_effects"] = sorted(effects["allocator_effects"], key=lambda item: item["effect_id"])
    effects["stack_effects"] = sorted(effects["stack_effects"], key=lambda item: item["effect_id"])
    effects["pairs"] = sorted(effects["pairs"], key=lambda item: item["pair_id"])
    effects["abstentions"] = sorted(
        effects["abstentions"],
        key=lambda item: (item["operand_key"], item["reason"]),
    )
    payload["comparisons"] = sorted(payload["comparisons"], key=lambda item: item["record_id"])
    payload["verdicts"] = sorted(payload["verdicts"], key=lambda item: (item["pair_id"], item["verdict_id"]))
    for verdict in payload["verdicts"]:
        verdict["proof_paths"] = sorted(verdict["proof_paths"])
        verdict["rejected_alternatives"] = sorted(verdict["rejected_alternatives"])
        verdict["failed_gates"] = sorted(verdict["failed_gates"])
        verdict["follow_up_commands"] = sorted(verdict["follow_up_commands"])
    for rule in payload["applied_rules"]:
        rule["input_record_ids"] = sorted(rule["input_record_ids"])
        rule["output_record_ids"] = sorted(rule["output_record_ids"])
    payload["applied_rules"] = sorted(
        payload["applied_rules"],
        key=lambda item: (
            item["rule_id"],
            item["input_record_ids"],
            item["output_record_ids"],
        ),
    )
    payload["missing_evidence"] = sorted(payload["missing_evidence"])
    payload["warnings"] = sorted(payload["warnings"])
    return payload


__all__ = [
    "AnalysisStatus",
    "AppliedRule",
    "CausalDiffReport",
    "CausalVerdict",
    "VerdictStatus",
    "build_report",
    "exit_code_for_report",
    "infer_pair",
    "report_to_canonical_dict",
]
