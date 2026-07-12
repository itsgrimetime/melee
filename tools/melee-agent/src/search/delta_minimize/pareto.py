"""Exact four-axis Pareto reduction for delta-minimize candidates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from .contracts import (
    AxisDistances,
    CandidateProfile,
    DeltaMinimizeError,
    ParetoGroup,
    ParetoSummary,
)


def dominates(a: AxisDistances, b: AxisDistances) -> bool:
    """Return whether *a* is no worse on every axis and better on one."""

    pairs = (
        (a.opcode, b.opcode),
        (a.color, b.color),
        (a.objobjects, b.objobjects),
        (a.stack_homes, b.stack_homes),
    )
    return all(x <= y for x, y in pairs) and any(x < y for x, y in pairs)


def reduce_pareto(
    profiles: Sequence[CandidateProfile],
    *,
    atom_count: int,
) -> ParetoSummary:
    """Reduce complete candidate evidence to the exact raw Pareto frontier."""

    incomplete = [
        profile.candidate_id
        for profile in profiles
        if profile.viable and (not profile.complete or profile.axes is None)
    ]
    if incomplete:
        raise DeltaMinimizeError(
            "incomplete-candidate-evidence",
            {"candidate_ids": incomplete},
        )

    viable = [profile for profile in profiles if profile.viable and profile.axes is not None]
    frontier = [
        profile
        for profile in viable
        if not any(
            other.candidate_id != profile.candidate_id and dominates(other.axes, profile.axes) for other in viable
        )
    ]
    return _build_summary(frontier, viable, atom_count=atom_count)


def _build_summary(
    frontier: Sequence[CandidateProfile],
    viable: Sequence[CandidateProfile],
    *,
    atom_count: int,
) -> ParetoSummary:
    frontier_by_vector: dict[AxisDistances, list[CandidateProfile]] = defaultdict(list)
    for profile in frontier:
        assert profile.axes is not None
        frontier_by_vector[profile.axes].append(profile)

    groups = tuple(
        _build_group(vector, frontier_by_vector[vector], atom_count=atom_count) for vector in sorted(frontier_by_vector)
    )
    ordered_frontier = sorted(frontier, key=_stable_mask_key)
    frontier_ids = tuple(profile.candidate_id for profile in ordered_frontier)

    exact_matches = sorted(
        (profile for profile in viable if profile.exact_object_match),
        key=_stable_mask_key,
    )
    exact_match_ids = tuple(profile.candidate_id for profile in exact_matches)

    zero = AxisDistances.zero()
    zero_groups = [group for group in groups if group.objective_vector == zero]
    zero_ids = tuple(candidate_id for group in zero_groups for candidate_id in group.candidate_ids)
    joint_ids = {
        candidate_id for group in zero_groups for candidate_id in (*group.minimal_from_left, *group.minimal_from_right)
    }
    frontier_by_id = {profile.candidate_id: profile for profile in ordered_frontier}
    joint_solutions = tuple(
        profile.candidate_id
        for profile in sorted(
            (frontier_by_id[candidate_id] for candidate_id in joint_ids),
            key=_stable_mask_key,
        )
    )

    if exact_matches:
        status = "matched"
    elif zero_groups:
        status = "joint-zero"
    else:
        status = "frontier"

    best_pool = {profile.candidate_id: profile for profile in ordered_frontier}
    best_pool.update({profile.candidate_id: profile for profile in exact_matches})
    best_next = min(
        best_pool.values(),
        key=lambda profile: _best_next_key(profile, atom_count=atom_count),
        default=None,
    )

    return ParetoSummary(
        status=status,
        candidate_ids=frontier_ids,
        groups=groups,
        best_next=None if best_next is None else best_next.candidate_id,
        exact_match_candidate_ids=exact_match_ids,
        joint_solutions=joint_solutions,
        joint_zero_all_candidate_ids=zero_ids,
    )


def _build_group(
    vector: AxisDistances,
    profiles: Sequence[CandidateProfile],
    *,
    atom_count: int,
) -> ParetoGroup:
    ordered = sorted(profiles, key=_stable_mask_key)
    from_left = min(
        ordered,
        key=lambda profile: (
            profile.mask.bit_count(),
            profile.changed_bytes_from_left,
            profile.mask,
            profile.candidate_id,
        ),
    )
    from_right = min(
        ordered,
        key=lambda profile: (
            atom_count - profile.mask.bit_count(),
            profile.changed_bytes_from_right,
            profile.mask,
            profile.candidate_id,
        ),
    )
    representative = min(
        ordered,
        key=lambda profile: (
            _min_parent_distance(profile, atom_count=atom_count),
            _min_changed_bytes(profile),
            profile.mask,
            profile.candidate_id,
        ),
    )
    return ParetoGroup(
        objective_vector=vector,
        candidate_ids=tuple(profile.candidate_id for profile in ordered),
        minimal_from_left=(from_left.candidate_id,),
        minimal_from_right=(from_right.candidate_id,),
        representative=representative.candidate_id,
    )


def _best_next_key(profile: CandidateProfile, *, atom_count: int) -> tuple[object, ...]:
    assert profile.axes is not None
    zero_axis_count = sum(
        (
            profile.axes.opcode == (0, 0),
            profile.axes.color == (0, 0, 0, 0, 0, 0),
            profile.axes.objobjects == (0, 0),
            profile.axes.stack_homes == (0, 0, 0, 0),
        )
    )
    return (
        not profile.exact_object_match,
        -zero_axis_count,
        profile.axes.opcode,
        profile.axes.color,
        profile.axes.objobjects,
        profile.axes.stack_homes,
        _min_parent_distance(profile, atom_count=atom_count),
        _min_changed_bytes(profile),
        profile.candidate_id,
    )


def _min_parent_distance(profile: CandidateProfile, *, atom_count: int) -> int:
    from_left = profile.mask.bit_count()
    return min(from_left, atom_count - from_left)


def _min_changed_bytes(profile: CandidateProfile) -> int:
    return min(profile.changed_bytes_from_left, profile.changed_bytes_from_right)


def _stable_mask_key(profile: CandidateProfile) -> tuple[int, str]:
    return profile.mask, profile.candidate_id
