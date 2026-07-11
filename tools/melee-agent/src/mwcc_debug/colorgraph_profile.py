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


def _has_coherent_iterations(rows: list) -> bool:
    return sorted(row.iter_idx for row in rows) == list(range(len(rows)))


def _resolve_alias_roots(
    direct_roots: Mapping[int, int],
    n_virtuals: int,
    blocked: set[int] | frozenset[int] = frozenset(),
) -> tuple[dict[int, int], set[int]]:
    """Resolve an alias forest, returning roots and nodes with no root."""
    resolved: dict[int, int] = {}
    unresolved = {ig_idx for ig_idx in blocked if 0 <= ig_idx < n_virtuals}
    for start in range(n_virtuals):
        if start in resolved or start in unresolved:
            continue
        trail: list[int] = []
        positions: dict[int, int] = {}
        current = start
        root: int | None = None
        while True:
            if current in resolved:
                root = resolved[current]
                break
            if current in unresolved:
                unresolved.update(trail)
                break
            if current in positions:
                unresolved.update(trail)
                break
            positions[current] = len(trail)
            trail.append(current)
            next_ig = direct_roots.get(current, current)
            if next_ig == current:
                root = current
                break
            if not 0 <= next_ig < n_virtuals:
                unresolved.update(trail)
                break
            current = next_ig
        if root is not None:
            for ig_idx in trail:
                resolved[ig_idx] = root
    return resolved, unresolved


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
        if ig_idx < 0:
            continue
        role_to_igs[role].add(ig_idx)
    ambiguous_roles = {role for role, igs in role_to_igs.items() if len(igs) != 1}

    incomplete = simplify_section is None or coalesce_section is None
    if simplify_section is not None and coalesce_section is not None:
        incomplete = incomplete or (
            simplify_section.n_class_regs <= 0
            or coalesce_section.n_virtuals <= 0
            or simplify_section.n_class_regs != coalesce_section.n_virtuals
        )
    incomplete = incomplete or (
        decision_section.result != 1
        or decision_section.n_nodes < 0
        or decision_section.n_nodes != len(decision_section.decisions)
        or not _has_coherent_iterations(decision_section.decisions)
        or any(
            decision.n_interferers < 0 or decision.n_interferers != len(decision.interferers)
            for decision in decision_section.decisions
        )
    )
    if simplify_section is not None:
        incomplete = incomplete or (
            len(simplify_section.entries) != len(decision_section.decisions)
            or not _has_coherent_iterations(simplify_section.entries)
        )
    if coalesce_section is not None:
        incomplete = incomplete or (
            coalesce_section.distinct_roots is None
            or coalesce_section.forced_count != len(coalesce_section.forced_overrides)
            or coalesce_section.truncated
            or not coalesce_section.exit_valid
        )
    unmapped_evidence = False
    out_of_range_evidence = False
    ambiguous_evidence_roles: set[int] = set()

    def stable_role(ig_idx: int) -> int | None:
        nonlocal out_of_range_evidence, unmapped_evidence
        if ig_idx < 0:
            return None
        if coalesce_section is not None and not 0 <= ig_idx < coalesce_section.n_virtuals:
            out_of_range_evidence = True
            return None
        role = role_map.get(ig_idx)
        if role is None:
            unmapped_evidence = True
            return None
        if role < 0:
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
        interferer_roles = [(other_ig, stable_role(other_ig)) for other_ig, _other_phys in decision.interferers]
        if decision.ig_idx < 0:
            continue
        if role is None:
            continue
        assignment_rows[role].append(decision.assigned_reg)
        select_roles.append(role)
        for other_ig, other_role in interferer_roles:
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
    conflicting_coalesce_roles: set[int] = set()
    if coalesce_section is not None:
        roots_by_alias: dict[int, set[int]] = defaultdict(set)
        invalid_coalesce_igs: set[int] = set()

        def coalesce_role(ig_idx: int) -> int | None:
            role = stable_role(ig_idx)
            if role is None:
                invalid_coalesce_igs.add(ig_idx)
            return role

        for alias_ig, root_ig in coalesce_section.mappings:
            alias_role = coalesce_role(alias_ig)
            root_role = coalesce_role(root_ig)
            if alias_role is None or root_role is None:
                incomplete = True
                if 0 <= alias_ig < coalesce_section.n_virtuals:
                    invalid_coalesce_igs.add(alias_ig)
            if not (0 <= alias_ig < coalesce_section.n_virtuals and 0 <= root_ig < coalesce_section.n_virtuals):
                incomplete = True
                continue
            roots_by_alias[alias_ig].add(root_ig)

        projection_blocked_igs = {
            ig_idx for ig_idx in invalid_coalesce_igs if 0 <= ig_idx < coalesce_section.n_virtuals
        }
        blocked_aliases = set(projection_blocked_igs)
        conflicting_aliases = {alias_ig for alias_ig, roots in roots_by_alias.items() if len(roots) > 1}
        blocked_aliases.update(conflicting_aliases)
        incomplete = incomplete or bool(conflicting_aliases)
        for alias_ig in conflicting_aliases:
            alias_role = stable_role(alias_ig)
            if alias_role is not None:
                conflicting_coalesce_roles.add(alias_role)

        final_roots = {alias_ig: next(iter(roots)) for alias_ig, roots in roots_by_alias.items() if len(roots) == 1}
        for alias_ig, old_root_ig, new_root_ig in coalesce_section.forced_overrides:
            endpoint_igs = (alias_ig, old_root_ig, new_root_ig)
            endpoint_roles = tuple(coalesce_role(ig_idx) for ig_idx in endpoint_igs)
            if any(role is None for role in endpoint_roles):
                incomplete = True
                invalid_endpoints = {
                    ig_idx
                    for ig_idx, role in zip(endpoint_igs, endpoint_roles)
                    if role is None and 0 <= ig_idx < coalesce_section.n_virtuals
                }
                blocked_aliases.update(invalid_endpoints)
                projection_blocked_igs.update(invalid_endpoints)
                if 0 <= alias_ig < coalesce_section.n_virtuals:
                    blocked_aliases.add(alias_ig)
                    projection_blocked_igs.add(alias_ig)
            if not all(0 <= ig_idx < coalesce_section.n_virtuals for ig_idx in endpoint_igs):
                incomplete = True
                if 0 <= alias_ig < coalesce_section.n_virtuals:
                    blocked_aliases.add(alias_ig)
                continue
            if alias_ig in blocked_aliases:
                incomplete = True
                continue
            current_root_ig = final_roots.get(alias_ig, alias_ig)
            if current_root_ig != old_root_ig:
                incomplete = True
                blocked_aliases.add(alias_ig)
                continue
            final_roots[alias_ig] = new_root_ig

        _, projection_unresolved_igs = _resolve_alias_roots(
            final_roots,
            coalesce_section.n_virtuals,
            projection_blocked_igs,
        )
        resolved_roots, unresolved_igs = _resolve_alias_roots(
            final_roots,
            coalesce_section.n_virtuals,
            blocked_aliases,
        )
        if unresolved_igs:
            incomplete = True
            for ig_idx in sorted(unresolved_igs):
                if ig_idx in projection_unresolved_igs:
                    continue
                role = stable_role(ig_idx)
                if role is not None:
                    conflicting_coalesce_roles.add(role)

        if coalesce_section.distinct_roots is not None:
            expected_distinct_roots = len(set(resolved_roots.values()))
            if (
                not 0 <= coalesce_section.distinct_roots <= coalesce_section.n_virtuals
                or len(resolved_roots) != coalesce_section.n_virtuals
                or coalesce_section.distinct_roots != expected_distinct_roots
            ):
                incomplete = True

        for alias_ig in sorted(final_roots):
            root_ig = resolved_roots.get(alias_ig)
            if root_ig is None or alias_ig == root_ig:
                continue
            alias_role = stable_role(alias_ig)
            root_role = stable_role(root_ig)
            if alias_role is not None and root_role is not None:
                coalesce_pairs.add((alias_role, root_role))

    observed_roles = {role for role in (*assignment_rows, *select_roles, *simplify_roles) if role >= 0}
    expected_roles = required | observed_roles
    assignment_counts = {role: len(regs) for role, regs in assignment_rows.items()}
    simplify_counts = Counter(simplify_roles)
    select_counts = Counter(select_roles)
    missing_roles = {
        role
        for role in expected_roles
        if assignment_counts.get(role, 0) != 1 or simplify_counts[role] != 1 or select_counts[role] != 1
    }
    missing_roles.update(ambiguous_evidence_roles)
    missing_roles.update(conflicting_coalesce_roles)
    incomplete = incomplete or unmapped_evidence or out_of_range_evidence or bool(missing_roles)

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


def _validate_profile_integrity(profile: ColorGraphProfile) -> None:
    """Require complete, one-to-one assignment/simplify/select role lanes."""
    if not profile.complete:
        raise ValueError("incomplete color graph profile cannot be compared")

    stable_roles = [role for role, _physical in profile.assignments]
    stable_roles.extend(profile.simplify_order)
    stable_roles.extend(profile.select_order)
    stable_roles.extend(role for edge in profile.interference_edges for role in edge)
    stable_roles.extend(role for pair in profile.coalesce_pairs for role in pair)
    stable_roles.extend(profile.spills)
    if any(role < 0 for role in stable_roles):
        raise ValueError("negative stable role in color graph profile")

    assignment_counts = Counter(role for role, _physical in profile.assignments)
    simplify_counts = Counter(profile.simplify_order)
    select_counts = Counter(profile.select_order)
    if (
        set(assignment_counts) != set(simplify_counts)
        or set(assignment_counts) != set(select_counts)
        or any(count != 1 for count in assignment_counts.values())
        or any(count != 1 for count in simplify_counts.values())
        or any(count != 1 for count in select_counts.values())
    ):
        raise ValueError("incomplete color graph profile cannot be compared")


def colorgraph_distance(
    candidate: ColorGraphProfile,
    donor: ColorGraphProfile,
    desired_phys: Mapping[int, int],
) -> ColorDistance:
    """Compare a candidate to absolute assignments and donor graph evidence."""
    required = set(desired_phys)
    if any(role < 0 for role in required):
        raise ValueError("negative stable role in desired physical assignments")
    for profile in (candidate, donor):
        _validate_profile_integrity(profile)
        assignment_counts = Counter(role for role, _physical in profile.assignments)
        simplify_counts = Counter(profile.simplify_order)
        select_counts = Counter(profile.select_order)
        if any(
            assignment_counts[role] != 1 or simplify_counts[role] != 1 or select_counts[role] != 1 for role in required
        ):
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
