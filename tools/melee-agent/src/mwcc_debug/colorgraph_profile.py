"""Role-anchored profiles and distances for MWCC color-graph evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import astuple, dataclass
from typing import Mapping

from .colorgraph_parser import parse_hook_events


@dataclass(frozen=True)
class ColorGraphProfile:
    assignments: tuple[tuple[int, int], ...]
    simplify_order: tuple[int, ...]
    select_order: tuple[int, ...]
    interference_edges: frozenset[tuple[int, int]]
    coalesce_pairs: frozenset[tuple[int, int]]
    spills: frozenset[int]
    complete: bool
    missing_roles: tuple[int, ...] = ()


@dataclass(frozen=True)
class ColorDistance:
    assignment_misses: int
    simplify_order_inversions: int
    select_order_inversions: int
    interference_edge_delta: int
    coalesce_delta: int
    spill_delta: int

    def as_tuple(self) -> tuple[int, ...]:
        return astuple(self)


def _matching_sections(sections: list, class_id: int) -> list:
    return [section for section in sections if section.class_id == class_id]


def _empty_profile(missing_roles: set[int] | frozenset[int]) -> ColorGraphProfile:
    return ColorGraphProfile(
        assignments=(),
        simplify_order=(),
        select_order=(),
        interference_edges=frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=False,
        missing_roles=tuple(sorted(missing_roles)),
    )


def build_colorgraph_profile(
    pcdump: str,
    function: str,
    class_id: int,
    role_map: Mapping[int, int],
    required_roles: set[int] | frozenset[int] | None = None,
) -> ColorGraphProfile:
    """Build one immutable function/class profile in stable-role identity.

    ``role_map`` maps candidate IG indices to stable original roles. Negative
    IG sentinels are parser metadata and are ignored. Every nonnegative IG in
    the selected evidence sections must have one unambiguous stable role;
    otherwise the returned profile is incomplete.
    """
    required = frozenset(required_roles or ())
    functions = [event for event in parse_hook_events(pcdump) if event.name == function]
    if len(functions) != 1:
        return _empty_profile(required)
    events = functions[0]

    decisions = _matching_sections(events.colorgraph_sections, class_id)
    simplify = _matching_sections(events.simplify_sections, class_id)
    coalesce = _matching_sections(events.coalesce_sections, class_id)
    if not decisions:
        return _empty_profile(required)

    decision_section = decisions[-1]
    simplify_section = simplify[-1] if simplify else None
    coalesce_section = coalesce[-1] if coalesce else None

    role_to_igs: dict[int, set[int]] = defaultdict(set)
    for ig_idx, role in role_map.items():
        role_to_igs[role].add(ig_idx)
    ambiguous_roles = {role for role, igs in role_to_igs.items() if len(igs) != 1}

    incomplete = not simplify or not coalesce
    unmapped_evidence = False
    ambiguous_evidence_roles: set[int] = set()

    def stable_role(ig_idx: int) -> int | None:
        nonlocal unmapped_evidence
        if ig_idx < 0:
            return None
        role = role_map.get(ig_idx)
        if role is None:
            unmapped_evidence = True
            return None
        if role in ambiguous_roles:
            ambiguous_evidence_roles.add(role)
            unmapped_evidence = True
            return None
        return role

    assignment_rows: dict[int, list[int]] = defaultdict(list)
    select_roles: list[int] = []
    interference_edges: set[tuple[int, int]] = set()
    for decision in sorted(decision_section.decisions, key=lambda item: item.iter_idx):
        role = stable_role(decision.ig_idx)
        if decision.ig_idx < 0:
            continue
        if role is None:
            for other_ig, _other_phys in decision.interferers:
                stable_role(other_ig)
            continue
        assignment_rows[role].append(decision.assigned_reg)
        select_roles.append(role)
        for other_ig, _other_phys in decision.interferers:
            other_role = stable_role(other_ig)
            if other_ig < 0 or other_role is None:
                continue
            if other_role == role:
                incomplete = True
                continue
            interference_edges.add(tuple(sorted((role, other_role))))

    if any(len(regs) != 1 for regs in assignment_rows.values()):
        incomplete = True
    assignments = tuple(sorted((role, regs[-1]) for role, regs in assignment_rows.items()))
    if len(select_roles) != len(set(select_roles)):
        incomplete = True

    simplify_roles: list[int] = []
    spills: set[int] = set()
    if simplify_section is not None:
        for entry in sorted(simplify_section.entries, key=lambda item: item.iter_idx):
            role = stable_role(entry.ig_idx)
            if entry.ig_idx < 0 or role is None:
                continue
            simplify_roles.append(role)
            if entry.spilled:
                spills.add(role)
    if len(simplify_roles) != len(set(simplify_roles)):
        incomplete = True

    coalesce_pairs: set[tuple[int, int]] = set()
    if coalesce_section is not None:
        for alias_ig, root_ig in coalesce_section.mappings:
            alias_role = stable_role(alias_ig)
            root_role = stable_role(root_ig)
            if alias_role is None or root_role is None:
                continue
            if alias_role == root_role:
                incomplete = True
                continue
            coalesce_pairs.add((alias_role, root_role))

    assignment_roles = set(assignment_rows)
    missing_roles = set(required - assignment_roles)
    missing_roles.update(ambiguous_evidence_roles)
    incomplete = incomplete or unmapped_evidence or bool(missing_roles)

    return ColorGraphProfile(
        assignments=assignments,
        simplify_order=tuple(simplify_roles),
        select_order=tuple(select_roles),
        interference_edges=frozenset(interference_edges),
        coalesce_pairs=frozenset(coalesce_pairs),
        spills=frozenset(spills),
        complete=not incomplete,
        missing_roles=tuple(sorted(missing_roles)),
    )


def _kendall_inversions(candidate: tuple[int, ...], donor: tuple[int, ...]) -> int:
    candidate_counts = Counter(candidate)
    donor_counts = Counter(donor)
    shared = {
        role
        for role in candidate_counts.keys() & donor_counts.keys()
        if candidate_counts[role] == donor_counts[role] == 1
    }
    candidate_order = [role for role in candidate if role in shared]
    donor_positions = {role: index for index, role in enumerate(donor) if role in shared}
    return sum(
        donor_positions[left] > donor_positions[right]
        for index, left in enumerate(candidate_order)
        for right in candidate_order[index + 1 :]
    )


def colorgraph_distance(
    candidate: ColorGraphProfile,
    donor: ColorGraphProfile,
    desired_phys: Mapping[int, int],
) -> ColorDistance:
    """Compare a candidate to absolute assignments and donor graph evidence."""
    if not candidate.complete or not donor.complete:
        raise ValueError("incomplete color graph profile cannot be compared")

    candidate_assignments = dict(candidate.assignments)
    return ColorDistance(
        assignment_misses=sum(candidate_assignments.get(role) != physical for role, physical in desired_phys.items()),
        simplify_order_inversions=_kendall_inversions(
            candidate.simplify_order,
            donor.simplify_order,
        ),
        select_order_inversions=_kendall_inversions(
            candidate.select_order,
            donor.select_order,
        ),
        interference_edge_delta=len(candidate.interference_edges.symmetric_difference(donor.interference_edges)),
        coalesce_delta=len(candidate.coalesce_pairs.symmetric_difference(donor.coalesce_pairs)),
        spill_delta=len(candidate.spills.symmetric_difference(donor.spills)),
    )
