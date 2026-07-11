"""Strict, storage-neutral inference over normalized causal evidence."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .canonical import canonical_bytes, stable_id
from .effects import DerivedEffects, EffectPair
from .graph import FrontierGraph
from .models import AdapterResult, ComparisonRecord, Confidence, EvidenceEdge, EvidenceNode
from .store import EvidenceQuery

_PATH_EDGE_KINDS = frozenset(
    {
        "uses-virtual",
        "defines-virtual",
        "maps-to-allocator-node",
        "has-color-decision",
        "interferes-with",
        "coalesces-with",
        "statement-has-enode",
        "enode-child",
        "enode-references-object",
        "object-owned-by-scope",
        "expression-represents-enode",
        "lowers-to",
        "materializes-as-stack-object",
        "bridge-candidate-materializes-stack-object",
        "bridge-has-stack-access",
        "bridge-has-source-expression",
    }
)
_OWNER_KINDS = frozenset({"source-expression", "objobject", "inline-scope"})
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

_GATE_1 = "gate-1-anchor-identity"
_GATE_2 = "gate-2-backend-role-identity"
_GATE_3 = "gate-3-shared-owner"
_GATE_4 = "gate-4-allocator-delta"
_GATE_5 = "gate-5-stack-delta"
_GATE_6 = "gate-6-unique-owner-chain"
_GATE_7 = "gate-7-proof-capable-path"
_GATE_8 = "gate-8-evidence-integrity"

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


def _all_simple_paths(
    query: EvidenceQuery,
    source_id: str,
    target_id: str,
) -> tuple[tuple[str, ...], ...]:
    """Enumerate every finite simple path in the caller-bounded evidence graph."""

    if source_id == target_id:
        return ((source_id,),)
    paths: list[tuple[str, ...]] = []

    def visit(node_id: str, visited: frozenset[str], path: tuple[str, ...]) -> None:
        neighbors: list[tuple[str, EvidenceEdge]] = []
        for edge in query.neighbors(node_id, _PATH_EDGE_KINDS, "both"):
            other = edge.target_id if edge.source_id == node_id else edge.source_id
            neighbors.append((other, edge))
        for other, edge in sorted(
            neighbors,
            key=lambda item: (item[1].kind, item[0], item[1].record_id),
        ):
            if other in visited:
                continue
            next_path = (*path, edge.record_id, other)
            if other == target_id:
                paths.append(next_path)
            else:
                visit(other, visited | {other}, next_path)

    visit(source_id, frozenset({source_id}), (source_id,))
    return tuple(sorted(set(paths), key=lambda path: (len(path), path)))


def _path_is_proof_capable(query: EvidenceQuery, path: tuple[str, ...]) -> bool:
    records = tuple(_record_for_id(query, record_id) for record_id in path)
    return all(record is not None and record.confidence in _PROOF_CONFIDENCES for record in records)


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
            allocator_paths = _all_simple_paths(query, owner.record_id, allocator.record_id)
            stack_paths = _all_simple_paths(query, owner.record_id, stack_target.record_id)
            if not allocator_paths or not stack_paths:
                continue
            all_paths = tuple(sorted((*allocator_paths, *stack_paths), key=lambda path: (len(path), path)))
            endpoint_alternatives.append(
                _OwnerAlternative(
                    comparison=comparison,
                    node=owner,
                    paths=all_paths,
                    proof_capable=(
                        comparison.confidence in _PROOF_CONFIDENCES
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
        rejected=tuple(sorted(set(rejected))),
        incomplete=incomplete,
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


def infer_pair(
    pair: EffectPair,
    query: EvidenceQuery,
    comparisons: Iterable[ComparisonRecord],
) -> CausalVerdict:
    """Apply the normative strict-inference table to one eligible effect pair."""

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
    role_proof_capable = role_comparison.confidence in _PROOF_CONFIDENCES
    role_registered = any(comparison.record_id == role_comparison.record_id for comparison in records)
    allocator_deltas = _bilateral_node_deltas(records, allocator_ids)
    stack_deltas = _bilateral_node_deltas(records, stack_ids)
    allocator_delta_proven = all(comparison.confidence in _PROOF_CONFIDENCES for comparison in allocator_deltas)
    stack_delta_proven = all(comparison.confidence in _PROOF_CONFIDENCES for comparison in stack_deltas)

    owner_enumeration = _owner_alternatives(pair, query, records)
    alternatives = owner_enumeration.alternatives
    rejected = owner_enumeration.rejected
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
    ]
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

    proof_paths = _shortest_paths(alternatives, role_comparison.record_id)
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
) -> CausalDiffReport:
    """Infer every pair and aggregate a deterministic versioned report."""

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
    inferred_verdicts = tuple(
        sorted(
            (
                infer_pair(pair, query, comparison_records)
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
        return {field.name: _canonical_value(getattr(value, field.name)) for field in fields(value)}
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
