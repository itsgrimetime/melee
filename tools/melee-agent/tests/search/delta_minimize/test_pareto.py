import json

import pytest

from src.search.delta_minimize.contracts import (
    AxisDistances,
    CandidateProfile,
    DeltaMinimizeError,
)
from src.search.delta_minimize.pareto import dominates, reduce_pareto


def profile(
    cid,
    mask,
    axes,
    *,
    exact=False,
    complete=True,
    changed_left=0,
    changed_right=0,
):
    return CandidateProfile(
        candidate_id=cid,
        mask=mask,
        source_hash=cid,
        source_path=f"/{cid}.c",
        viable=True,
        compile_status="ok",
        axes=axes,
        complete=complete,
        exact_object_match=exact,
        changed_bytes_from_left=changed_left,
        changed_bytes_from_right=changed_right,
    )


def distances(value):
    return AxisDistances((value, 0), (0, 0, 0, 0, 0, 0), (0, 0), (0, 0, 0, 0))


def test_raw_frontier_keeps_all_masks_and_minimizes_both_directions():
    vector = AxisDistances((0, 0), (1, 0, 0, 0, 0, 0), (0, 0), (0, 0, 0, 0))
    result = reduce_pareto(
        [profile("left-near", 0b001, vector), profile("right-near", 0b110, vector)],
        atom_count=3,
    )
    assert result.candidate_ids == ("left-near", "right-near")
    assert result.groups[0].minimal_from_left == ("left-near",)
    assert result.groups[0].minimal_from_right == ("right-near",)


def test_viable_incomplete_profile_blocks_exact_reduction():
    complete = profile("complete", 0, AxisDistances.zero())
    incomplete = profile("incomplete", 1, None, complete=False)
    with pytest.raises(DeltaMinimizeError, match="incomplete-candidate-evidence") as error:
        reduce_pareto([complete, incomplete], atom_count=1)
    assert error.value.details == {"candidate_ids": ["incomplete"]}


def test_viable_complete_profile_without_axes_blocks_exact_reduction():
    complete = profile("complete", 0, AxisDistances.zero())
    missing_axes = profile("missing-axes", 1, None, complete=True)
    with pytest.raises(DeltaMinimizeError, match="incomplete-candidate-evidence") as error:
        reduce_pareto([complete, missing_axes], atom_count=1)
    assert error.value.details == {"candidate_ids": ["missing-axes"]}


def test_exact_match_status_precedes_proxy_joint_zero():
    nonzero = AxisDistances((0, 0), (0, 0, 0, 0, 0, 0), (1, 0), (0, 0, 0, 0))
    result = reduce_pareto(
        [profile("winner", 0, nonzero, exact=True), profile("proxy-zero", 1, AxisDistances.zero())],
        atom_count=1,
    )
    assert result.status == "matched"
    assert result.exact_match_candidate_ids == ("winner",)


def test_dominance_compares_each_axis_tuple_lexicographically():
    lexicographically_better = AxisDistances(
        (0, 99),
        (0, 0, 0, 0, 0, 0),
        (0, 0),
        (0, 0, 0, 0),
    )
    lexicographically_worse = AxisDistances(
        (1, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0),
        (0, 0, 0, 0),
    )
    assert dominates(lexicographically_better, lexicographically_worse)
    assert not dominates(lexicographically_worse, lexicographically_better)
    assert not dominates(lexicographically_better, lexicographically_better)


def test_directional_reduction_uses_changed_bytes_before_mask_order():
    vector = distances(1)
    result = reduce_pareto(
        [
            profile("low-mask", 0b001, vector, changed_left=9, changed_right=8),
            profile("low-left-bytes", 0b010, vector, changed_left=2, changed_right=7),
            profile("low-right-bytes", 0b100, vector, changed_left=8, changed_right=1),
        ],
        atom_count=3,
    )
    assert result.groups[0].minimal_from_left == ("low-left-bytes",)
    assert result.groups[0].minimal_from_right == ("low-right-bytes",)


def test_directional_reduction_uses_stable_numeric_mask_after_changed_bytes():
    vector = distances(1)
    result = reduce_pareto(
        [
            profile("higher-mask", 0b010, vector, changed_left=3, changed_right=3),
            profile("lower-mask", 0b001, vector, changed_left=3, changed_right=3),
        ],
        atom_count=2,
    )
    assert result.groups[0].minimal_from_left == ("lower-mask",)
    assert result.groups[0].minimal_from_right == ("lower-mask",)


def test_joint_zero_retains_raw_membership_and_unions_directional_solutions():
    zero = AxisDistances.zero()
    result = reduce_pareto(
        [profile("left", 0, zero), profile("middle", 1, zero), profile("right", 3, zero)],
        atom_count=2,
    )
    assert result.status == "joint-zero"
    assert result.joint_zero_all_candidate_ids == ("left", "middle", "right")
    assert result.joint_solutions == ("left", "right")


def test_exact_matches_are_retained_when_proxy_axes_are_dominated():
    result = reduce_pareto(
        [
            profile("proxy-best", 0, AxisDistances.zero()),
            profile("exact", 1, distances(1), exact=True),
        ],
        atom_count=1,
    )
    assert result.candidate_ids == ("proxy-best",)
    assert result.exact_match_candidate_ids == ("exact",)
    assert result.best_next == "exact"


def test_best_next_uses_axis_count_vectors_distance_bytes_then_candidate_id():
    one_zero_axis = AxisDistances((0, 0), (1, 0, 0, 0, 0, 0), (1, 0), (1, 0, 0, 0))
    two_zero_axes = AxisDistances((0, 0), (2, 0, 0, 0, 0, 0), (0, 0), (1, 0, 0, 0))
    result = reduce_pareto(
        [
            profile("fewer-zero-axes", 0, one_zero_axis),
            profile("more-zero-axes", 0b111, two_zero_axes, changed_left=99, changed_right=99),
        ],
        atom_count=3,
    )
    assert result.best_next == "more-zero-axes"

    same_vector = distances(1)
    result = reduce_pareto(
        [
            profile("near-left", 0b001, same_vector, changed_left=9, changed_right=9),
            profile("near-right-fewer-bytes", 0b110, same_vector, changed_left=7, changed_right=2),
        ],
        atom_count=3,
    )
    assert result.best_next == "near-right-fewer-bytes"

    result = reduce_pareto(
        [profile("z-id", 0, same_vector), profile("a-id", 0, same_vector)],
        atom_count=0,
    )
    assert result.best_next == "a-id"


def test_contracts_serialize_with_exact_json_friendly_field_names():
    candidate = profile("candidate", 1, AxisDistances.zero(), changed_left=3, changed_right=4)
    summary = reduce_pareto([candidate], atom_count=1)

    candidate_data = candidate.to_dict()
    assert tuple(candidate_data) == (
        "candidate_id",
        "mask",
        "source_hash",
        "source_path",
        "viable",
        "compile_status",
        "axes",
        "complete",
        "exact_object_match",
        "blockers",
        "changed_bytes_from_left",
        "changed_bytes_from_right",
    )
    summary_data = summary.to_dict()
    assert tuple(summary_data) == (
        "status",
        "candidate_ids",
        "groups",
        "best_next",
        "exact_match_candidate_ids",
        "joint_solutions",
        "joint_zero_all_candidate_ids",
    )
    assert summary_data["groups"][0]["objective_vector"] == AxisDistances.zero().to_dict()
    json.dumps(candidate_data)
    json.dumps(summary_data)
