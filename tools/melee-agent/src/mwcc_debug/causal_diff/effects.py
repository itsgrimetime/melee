"""Derive canonical allocator and stack effects from an anchor alignment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Mapping

from .alignment import (
    AbstentionReason,
    AnchorAlignment,
    EffectAbstention,
    RolePair,
    owner_alignment_record_is_authoritative,
)
from .canonical import stable_id
from .differ import owner_delta_record_is_authoritative
from .graph import FrontierGraph
from .legacy_ownership import legacy_reachable_records
from .models import ComparisonRecord, EvidenceNode
from .owner_certificate import (
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerSemanticState,
)
from .store import canonical_record_bytes

EffectDirection = Literal[
    "first-exact-second-mismatch",
    "first-mismatch-second-exact",
    "both-exact",
    "both-mismatch-same",
    "both-mismatch-different",
]
_OWNER_CORRESPONDENCE_PARSER = "causal-backend-owner-alignment.v2"
_OWNER_DELTA_PARSER = "causal-frontier-differ.v1"


def _canonical_comparison_records(
    comparisons: Iterable[ComparisonRecord],
) -> tuple[ComparisonRecord, ...]:
    by_content: dict[bytes, ComparisonRecord] = {}
    for comparison in comparisons:
        key = canonical_record_bytes(comparison)
        retained = by_content.get(key)
        if retained is None or (
            not _owner_record_is_authoritative(retained) and _owner_record_is_authoritative(comparison)
        ):
            by_content[key] = comparison
    return tuple(by_content[key] for key in sorted(by_content))


def _owner_record_is_authoritative(record: ComparisonRecord) -> bool:
    if record.relation_kind in {
        "backend-owner-corresponds-to",
        "backend-owner-abstained",
    }:
        return owner_alignment_record_is_authoritative(record)
    if record.relation_kind == "backend-owner-state-changed":
        return owner_delta_record_is_authoritative(record)
    return False


@dataclass(frozen=True, slots=True)
class AllocatorEffect:
    effect_id: str
    operand_key: str
    expected_phys: int
    first_label: str
    first_phys: int | None
    second_label: str
    second_phys: int | None
    direction: EffectDirection
    role_correspondence: RolePair

    @property
    def operand_keys(self) -> tuple[str, ...]:
        return tuple(self.operand_key.split("+"))


@dataclass(frozen=True, slots=True)
class StackEffect:
    effect_id: str
    role_key: str
    expected_offset: int | None
    first_label: str
    first_offset: int | None
    second_label: str
    second_offset: int | None
    direction: EffectDirection
    owner_record_ids: tuple[str, ...]
    owner_operand_key: str | None = None


@dataclass(frozen=True, slots=True)
class EffectPair:
    pair_id: str
    allocator: AllocatorEffect
    stack: StackEffect
    allocator_exact_stack_mismatch_label: str
    allocator_mismatch_stack_exact_label: str


@dataclass(frozen=True, slots=True)
class DerivedEffects:
    allocator_effects: tuple[AllocatorEffect, ...]
    stack_effects: tuple[StackEffect, ...]
    pairs: tuple[EffectPair, ...]
    abstentions: tuple[EffectAbstention, ...]


def _label(graph: FrontierGraph) -> str:
    return str(graph.bundle.label)


def _assigned_phys(node: EvidenceNode) -> int | None:
    for key in ("assigned_phys", "assigned_reg", "physical_register", "selected_reg", "color"):
        value = node.attributes.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _direction(
    expected: object,
    first: object,
    second: object,
) -> EffectDirection:
    first_exact = first == expected
    second_exact = second == expected
    if first_exact and second_exact:
        return "both-exact"
    if first_exact:
        return "first-exact-second-mismatch"
    if second_exact:
        return "first-mismatch-second-exact"
    return "both-mismatch-same" if first == second else "both-mismatch-different"


def _operand_sort_key(key: str) -> tuple[int, int, str]:
    kind, _, position = key.partition(":")
    try:
        parsed_position = int(position)
    except ValueError:
        parsed_position = 0
    return (0 if kind == "def" else 1, parsed_position, key)


def _allocator_effects(alignment: AnchorAlignment) -> tuple[AllocatorEffect, ...]:
    roles_by_key = {role.key: role for role in alignment.operand_roles}
    tied: dict[tuple[str, str], list[str]] = {}
    for key, pair in alignment.by_operand.items():
        tied.setdefault((pair.left.record_id, pair.right.record_id), []).append(key)

    effects: list[AllocatorEffect] = []
    for _identity, keys in sorted(tied.items(), key=lambda item: tuple(_operand_sort_key(key) for key in item[1])):
        ordered_keys = sorted(keys, key=_operand_sort_key)
        roles = tuple(roles_by_key[key] for key in ordered_keys)
        expected_values = {role.expected_phys for role in roles}
        if len(expected_values) != 1:
            continue
        expected = next(iter(expected_values))
        pair = alignment.by_operand[ordered_keys[0]]
        first_phys = _assigned_phys(pair.left)
        second_phys = _assigned_phys(pair.right)
        operand_key = "+".join(ordered_keys)
        effects.append(
            AllocatorEffect(
                effect_id=stable_id(
                    alignment.analysis_id,
                    "allocator-effect",
                    {
                        "operands": ordered_keys,
                        "expected": expected,
                        "first": (pair.left_label, pair.left.record_id, first_phys),
                        "second": (pair.right_label, pair.right.record_id, second_phys),
                    },
                ),
                operand_key=operand_key,
                expected_phys=expected,
                first_label=pair.left_label,
                first_phys=first_phys,
                second_label=pair.right_label,
                second_phys=second_phys,
                direction=_direction(expected, first_phys, second_phys),
                role_correspondence=pair,
            )
        )
    return tuple(effects)


def _reachable_records(graph: FrontierGraph, roots: Iterable[str]) -> tuple[frozenset[str], frozenset[str]]:
    return legacy_reachable_records(graph, roots)


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


def _trusted_stored_certificate(
    graph: FrontierGraph,
    record_id: str,
) -> EvidenceNode | None:
    certificate = graph.backend.owner_certificates.certificate(record_id)
    stored = graph.store.get_node(record_id)
    if (
        certificate is None
        or stored is None
        or stored.kind != "owner-proof-certificate"
        or canonical_record_bytes(stored) != canonical_record_bytes(certificate)
    ):
        return None
    return certificate


def _sole_untainted_unique_certificate(
    graph: FrontierGraph,
    role: OwnerRoleKey,
    record_id: str,
) -> EvidenceNode | None:
    result = graph.backend.owner_certificates
    resolution = result.resolution_for(role)
    certificate = _trusted_stored_certificate(graph, record_id)
    if (
        certificate is None
        or result.global_rejections
        or resolution.rejections
        or resolution.status is not OwnerResolutionStatus.UNIQUE
        or resolution.certificate_record_ids != (record_id,)
        or _owner_role(certificate.attributes.get("role")) != role
    ):
        return None
    return certificate


def _certificate_covered_stack_roles(
    graphs: tuple[FrontierGraph, FrontierGraph],
    allocator_effects: tuple[AllocatorEffect, ...],
    comparisons: tuple[ComparisonRecord, ...],
) -> frozenset[str]:
    graphs_by_compile = {str(graph.bundle.compile_id): graph for graph in graphs}
    allocator_operands = {operand_key for effect in allocator_effects for operand_key in effect.operand_keys}
    covered: set[str] = set()
    for comparison in comparisons:
        if (
            comparison.relation_kind != "backend-owner-corresponds-to"
            or not owner_alignment_record_is_authoritative(comparison)
            or comparison.provenance.parser != _OWNER_CORRESPONDENCE_PARSER
            or comparison.left_record_id is None
            or comparison.right_record_id is None
            or frozenset(comparison.attributes) != {"role"}
        ):
            continue
        role = _owner_role(comparison.attributes.get("role"))
        left_graph = graphs_by_compile.get(comparison.left_compile_id)
        right_graph = graphs_by_compile.get(comparison.right_compile_id)
        if (
            role is None
            or role.operand_key not in allocator_operands
            or left_graph is None
            or right_graph is None
            or not {
                comparison.left_record_id,
                comparison.right_record_id,
            }.issubset(comparison.provenance.input_record_ids)
        ):
            continue
        left = _sole_untainted_unique_certificate(
            left_graph,
            role,
            comparison.left_record_id,
        )
        right = _sole_untainted_unique_certificate(
            right_graph,
            role,
            comparison.right_record_id,
        )
        if (
            left is not None
            and right is not None
            and left.compile_id == comparison.left_compile_id
            and right.compile_id == comparison.right_compile_id
        ):
            covered.add(role.semantic_stack_role)
    return frozenset(covered)


def _certificate_stack_effects(
    alignment: AnchorAlignment,
    graphs: tuple[FrontierGraph, FrontierGraph],
    allocator_effects: tuple[AllocatorEffect, ...],
    comparisons: tuple[ComparisonRecord, ...],
) -> tuple[tuple[StackEffect, ...], tuple[EffectAbstention, ...]]:
    graphs_by_compile = {str(graph.bundle.compile_id): graph for graph in graphs}
    allocator_operands = {operand_key for effect in allocator_effects for operand_key in effect.operand_keys}
    correspondences = tuple(
        comparison
        for comparison in comparisons
        if comparison.relation_kind == "backend-owner-corresponds-to"
        and owner_alignment_record_is_authoritative(comparison)
        and comparison.provenance.parser == _OWNER_CORRESPONDENCE_PARSER
        and comparison.left_record_id is not None
        and comparison.right_record_id is not None
    )
    effects: list[StackEffect] = []
    abstentions: list[EffectAbstention] = []
    for delta in sorted(comparisons, key=lambda item: item.record_id):
        if (
            delta.relation_kind != "backend-owner-state-changed"
            or not owner_delta_record_is_authoritative(delta)
            or delta.provenance.parser != _OWNER_DELTA_PARSER
            or delta.left_record_id is None
            or delta.right_record_id is None
        ):
            continue
        matching = tuple(
            comparison
            for comparison in correspondences
            if comparison.left_compile_id == delta.left_compile_id
            and comparison.left_record_id == delta.left_record_id
            and comparison.right_compile_id == delta.right_compile_id
            and comparison.right_record_id == delta.right_record_id
            and comparison.attributes.get("role") == delta.attributes.get("role")
        )
        if len(matching) != 1:
            continue
        correspondence = matching[0]
        required_provenance = {
            correspondence.record_id,
            delta.left_record_id,
            delta.right_record_id,
        }
        if not required_provenance.issubset(delta.provenance.input_record_ids):
            continue
        left_graph = graphs_by_compile.get(delta.left_compile_id)
        right_graph = graphs_by_compile.get(delta.right_compile_id)
        if left_graph is None or right_graph is None:
            continue
        authorization_role = _owner_role(delta.attributes.get("role"))
        if authorization_role is None:
            continue
        left = _sole_untainted_unique_certificate(
            left_graph,
            authorization_role,
            delta.left_record_id,
        )
        right = _sole_untainted_unique_certificate(
            right_graph,
            authorization_role,
            delta.right_record_id,
        )
        if left is None or right is None:
            continue
        roles = tuple(
            _owner_role(value)
            for value in (
                correspondence.attributes.get("role"),
                delta.attributes.get("role"),
                left.attributes.get("role"),
                right.attributes.get("role"),
            )
        )
        left_state = _owner_state(delta.attributes.get("left_semantic_state"))
        right_state = _owner_state(delta.attributes.get("right_semantic_state"))
        if (
            any(role is None for role in roles)
            or len(set(roles)) != 1
            or left_state is None
            or right_state is None
            or left_state != _owner_state(left.attributes.get("semantic_state"))
            or right_state != _owner_state(right.attributes.get("semantic_state"))
        ):
            continue
        role = roles[0]
        assert role is not None
        if role.operand_key not in allocator_operands:
            continue
        if (left_state.stack_offset, left_state.stack_size) == (
            right_state.stack_offset,
            right_state.stack_size,
        ):
            continue
        expected_values = {
            interval
            for graph in (left_graph, right_graph)
            if (interval := graph.frame.expected_stack_roles.get(role.semantic_stack_role)) is not None
        }
        if not expected_values:
            abstentions.append(
                EffectAbstention(
                    role.operand_key,
                    AbstentionReason.MISSING_EXPECTED_LAYOUT,
                )
            )
            continue
        if len(expected_values) != 1:
            abstentions.append(
                EffectAbstention(
                    role.operand_key,
                    AbstentionReason.CONTRADICTORY_EXPECTED_LAYOUT,
                )
            )
            continue
        expected = next(iter(expected_values))
        left_exact = left_state.stack_offset == expected[0] and left_state.stack_size == expected[1] - expected[0]
        right_exact = right_state.stack_offset == expected[0] and right_state.stack_size == expected[1] - expected[0]
        effects.append(
            StackEffect(
                effect_id=stable_id(
                    alignment.analysis_id,
                    "certified-stack-effect",
                    {
                        "role": role.as_json(),
                        "correspondence": correspondence.record_id,
                        "delta": delta.record_id,
                        "left": (left.record_id, left_state.as_json()),
                        "right": (right.record_id, right_state.as_json()),
                    },
                ),
                role_key=role.semantic_stack_role,
                expected_offset=expected[0],
                first_label=_label(left_graph),
                first_offset=left_state.stack_offset,
                second_label=_label(right_graph),
                second_offset=right_state.stack_offset,
                direction=_direction(True, left_exact, right_exact),
                owner_record_ids=tuple(sorted((left.record_id, right.record_id))),
                owner_operand_key=role.operand_key,
            )
        )
    return (
        tuple(sorted(effects, key=lambda effect: (effect.role_key, effect.effect_id))),
        tuple(abstentions),
    )


def _stack_shape(node: EvidenceNode | None) -> tuple[object, ...] | None:
    if node is None:
        return None
    attributes = node.attributes
    return (
        attributes.get("start"),
        attributes.get("end"),
        attributes.get("size"),
        attributes.get("layout_order", attributes.get("symbolic_assignment_order")),
        attributes.get("access_interval", attributes.get("materialization_interval")),
    )


def _stack_offset(node: EvidenceNode | None) -> int | None:
    if node is None:
        return None
    value = node.attributes.get("start", node.attributes.get("offset"))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _stack_exact(node: EvidenceNode | None, expected: tuple[int, int]) -> bool:
    if node is None:
        return False
    start, end = expected
    return _stack_offset(node) == start and node.attributes.get("size") == end - start


def _current_stack_candidates(graph: FrontierGraph, role_key: str) -> tuple[EvidenceNode, ...]:
    candidates: dict[str, EvidenceNode] = {}
    mapped_id = graph.frame.current_stack_nodes.get(role_key)
    if mapped_id is not None and (mapped := graph.store.get_node(mapped_id)) is not None:
        candidates[mapped.record_id] = mapped
    for node in graph.store.find_nodes(str(graph.bundle.compile_id), "stack-object"):
        if node.attributes.get("side") != "current":
            continue
        source_symbols = node.attributes.get("source_symbols", ())
        role_names = {
            str(node.role_key or ""),
            str(node.attributes.get("symbol") or ""),
            *(str(item) for item in source_symbols if isinstance(source_symbols, (list, tuple))),
        }
        if role_key in role_names:
            candidates[node.record_id] = node
    return tuple(candidates[record_id] for record_id in sorted(candidates))


def _stack_effects(
    alignment: AnchorAlignment,
    graphs: tuple[FrontierGraph, FrontierGraph],
    allocator_effects: tuple[AllocatorEffect, ...],
    suppressed_role_keys: frozenset[str] = frozenset(),
) -> tuple[tuple[StackEffect, ...], tuple[EffectAbstention, ...]]:
    graphs_by_label = {_label(graph): graph for graph in graphs}
    roots_by_label: dict[str, set[str]] = {label: set() for label in graphs_by_label}
    for effect in allocator_effects:
        roots_by_label[effect.first_label].add(effect.role_correspondence.left.record_id)
        roots_by_label[effect.second_label].add(effect.role_correspondence.right.record_id)
    reachable = {label: _reachable_records(graphs_by_label[label], roots) for label, roots in roots_by_label.items()}
    first_label, second_label = sorted(graphs_by_label)
    first_graph, second_graph = graphs_by_label[first_label], graphs_by_label[second_label]
    roles = sorted(
        (set(first_graph.frame.expected_stack_roles) | set(second_graph.frame.expected_stack_roles))
        - suppressed_role_keys
    )
    effects: list[StackEffect] = []
    abstentions: list[EffectAbstention] = []
    for role_key in roles:
        expected_values = {
            interval
            for graph in (first_graph, second_graph)
            if (interval := graph.frame.expected_stack_roles.get(role_key)) is not None
        }
        if not expected_values:
            abstentions.append(EffectAbstention(role_key, AbstentionReason.MISSING_EXPECTED_LAYOUT))
            continue
        if len(expected_values) != 1:
            abstentions.append(EffectAbstention(role_key, AbstentionReason.CONTRADICTORY_EXPECTED_LAYOUT))
            continue
        expected = next(iter(expected_values))
        first_candidates = _current_stack_candidates(first_graph, role_key)
        second_candidates = _current_stack_candidates(second_graph, role_key)
        if len(first_candidates) > 1 or len(second_candidates) > 1:
            candidate_ids = tuple(
                sorted(
                    node.record_id
                    for candidates in (first_candidates, second_candidates)
                    if len(candidates) > 1
                    for node in candidates
                )
            )
            abstentions.append(
                EffectAbstention(
                    role_key,
                    AbstentionReason.AMBIGUOUS_STACK_OBJECT,
                    missing_record_ids=candidate_ids,
                    follow_up_commands=("melee-agent debug inspect stack-homes --help",),
                )
            )
            continue
        first_node = first_candidates[0] if first_candidates else None
        second_node = second_candidates[0] if second_candidates else None
        first_reachable = first_node is not None and first_node.record_id in reachable[first_label][0]
        second_reachable = second_node is not None and second_node.record_id in reachable[second_label][0]
        uniquely_mapped_pair = (
            first_node is not None
            and second_node is not None
            and first_graph.frame.current_stack_nodes.get(role_key) == first_node.record_id
            and second_graph.frame.current_stack_nodes.get(role_key) == second_node.record_id
        )
        if not first_reachable and not second_reachable and not uniquely_mapped_pair:
            continue
        if not uniquely_mapped_pair:
            first_node = first_node if first_reachable else None
            second_node = second_node if second_reachable else None
        if _stack_shape(first_node) == _stack_shape(second_node):
            continue
        first_exact = _stack_exact(first_node, expected)
        second_exact = _stack_exact(second_node, expected)
        direction = _direction(True, first_exact, second_exact)
        owners: set[str] = set()
        for label, node in ((first_label, first_node), (second_label, second_node)):
            if node is not None:
                owners.add(node.record_id)
                owners.update(reachable[label][1])
        effects.append(
            StackEffect(
                effect_id=stable_id(
                    alignment.analysis_id,
                    "stack-effect",
                    {
                        "role_key": role_key,
                        "expected": expected,
                        "first": (first_label, _stack_shape(first_node)),
                        "second": (second_label, _stack_shape(second_node)),
                    },
                ),
                role_key=role_key,
                expected_offset=expected[0],
                first_label=first_label,
                first_offset=_stack_offset(first_node),
                second_label=second_label,
                second_offset=_stack_offset(second_node),
                direction=direction,
                owner_record_ids=tuple(sorted(owners)),
            )
        )
    return tuple(sorted(effects, key=lambda effect: (effect.role_key, effect.effect_id))), tuple(abstentions)


def _quality_by_label(first_label: str, second_label: str, direction: EffectDirection) -> dict[str, str]:
    if direction == "both-exact":
        return {first_label: "exact", second_label: "exact"}
    if direction == "first-exact-second-mismatch":
        return {first_label: "exact", second_label: "mismatch"}
    if direction == "first-mismatch-second-exact":
        return {first_label: "mismatch", second_label: "exact"}
    return {first_label: "mismatch", second_label: "mismatch"}


def _effect_pairs(
    analysis_id: str,
    allocator_effects: tuple[AllocatorEffect, ...],
    stack_effects: tuple[StackEffect, ...],
) -> tuple[EffectPair, ...]:
    pairs: list[EffectPair] = []
    for allocator in allocator_effects:
        allocator_quality = _quality_by_label(allocator.first_label, allocator.second_label, allocator.direction)
        for stack in stack_effects:
            if stack.owner_operand_key is not None and stack.owner_operand_key not in allocator.operand_keys:
                continue
            stack_quality = _quality_by_label(stack.first_label, stack.second_label, stack.direction)
            eligible = [
                label
                for label in sorted(allocator_quality)
                if allocator_quality[label] == "exact" and stack_quality.get(label) == "mismatch"
            ]
            if len(eligible) != 1:
                continue
            exact_stack_mismatch = eligible[0]
            other = next(label for label in sorted(allocator_quality) if label != exact_stack_mismatch)
            if allocator_quality[other] != "mismatch" or stack_quality.get(other) != "exact":
                continue
            pairs.append(
                EffectPair(
                    pair_id=stable_id(
                        analysis_id,
                        "effect-pair",
                        (allocator.effect_id, stack.effect_id),
                    ),
                    allocator=allocator,
                    stack=stack,
                    allocator_exact_stack_mismatch_label=exact_stack_mismatch,
                    allocator_mismatch_stack_exact_label=other,
                )
            )
    return tuple(sorted(pairs, key=lambda pair: (pair.allocator.effect_id, pair.stack.effect_id, pair.pair_id)))


def derive_effects(
    alignment: AnchorAlignment,
    graphs: Iterable[FrontierGraph],
    comparisons: Iterable[ComparisonRecord] = (),
) -> DerivedEffects:
    """Derive effects with label-sorted direction independent of CLI order."""

    graph_pair = tuple(graphs)
    if len(graph_pair) != 2:
        raise ValueError("effect derivation requires exactly two frontiers")
    ordered = tuple(sorted(graph_pair, key=_label))
    comparison_records = _canonical_comparison_records(comparisons)
    allocator_effects = _allocator_effects(alignment)
    certificate_covered_roles = _certificate_covered_stack_roles(
        ordered,
        allocator_effects,
        comparison_records,
    )
    legacy_stack_effects, legacy_stack_abstentions = _stack_effects(
        alignment,
        ordered,
        allocator_effects,
        suppressed_role_keys=certificate_covered_roles,
    )
    certificate_stack_effects, certificate_stack_abstentions = _certificate_stack_effects(
        alignment,
        ordered,
        allocator_effects,
        comparison_records,
    )
    stack_effects = tuple(
        sorted(
            (*legacy_stack_effects, *certificate_stack_effects),
            key=lambda effect: (effect.role_key, effect.effect_id),
        )
    )
    return DerivedEffects(
        allocator_effects=allocator_effects,
        stack_effects=stack_effects,
        pairs=_effect_pairs(alignment.analysis_id, allocator_effects, stack_effects),
        abstentions=tuple(
            sorted(
                (
                    *alignment.abstentions,
                    *legacy_stack_abstentions,
                    *certificate_stack_abstentions,
                ),
                key=lambda item: (item.operand_key, item.reason.value),
            )
        ),
    )


__all__ = [
    "AllocatorEffect",
    "DerivedEffects",
    "EffectDirection",
    "EffectPair",
    "StackEffect",
    "derive_effects",
]
