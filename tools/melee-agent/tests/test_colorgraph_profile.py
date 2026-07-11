from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.mwcc_debug.colorgraph_profile import (
    ColorDistance,
    ColorGraphProfile,
    build_colorgraph_profile,
    colorgraph_distance,
)

DONOR_PCDUMP = """\
Starting function other
COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
iter ig_idx reg degree nIntfr flags
0 99 r31 0 0 0x00

Starting function f
[COALESCE] enter class=0 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  66 -> 70
[COALESCE] exit class=0 n_virtuals=80 distinct_roots=79 forced=0

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 66 1 1 0x00
1 70 1 1 0x08 SPILLED

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
iter ig_idx reg degree nIntfr flags
0 66 r25 1 1 0x00
  interferers: 70=r30
1 70 r30 1 1 0x00
  interferers: 66=r25
"""


CANDIDATE_PCDUMP = """\
Starting function f
[COALESCE] enter class=1 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  58 -> 75
[COALESCE] exit class=1 n_virtuals=80 distinct_roots=79 forced=0

[COALESCE] enter class=0 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  58 -> 75
[COALESCE] exit class=0 n_virtuals=80 distinct_roots=79 forced=0

SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 75 0 0 0x00

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 58 1 1 0x00
1 75 1 1 0x08 SPILLED

COLORGRAPH DECISIONS (class=1, result=1, n_nodes=1)
iter ig_idx reg degree nIntfr flags
0 75 r1 0 0 0x00

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
iter ig_idx reg degree nIntfr flags
0 58 r22 1 1 0x00
  interferers: 75=r30
1 75 r30 1 1 0x00
  interferers: 58=r22
"""


def test_renumbered_igs_compare_by_stable_roles() -> None:
    donor = build_colorgraph_profile(DONOR_PCDUMP, "f", 0, {66: 1, 70: 2})
    candidate = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1, 75: 2})

    assert candidate == ColorGraphProfile(
        assignments=((1, 22), (2, 30)),
        simplify_order=(1, 2),
        select_order=(1, 2),
        interference_edges=frozenset({(1, 2)}),
        coalesce_pairs=frozenset({(1, 2)}),
        spills=frozenset({2}),
        complete=True,
    )
    distance = colorgraph_distance(candidate, donor, desired_phys={1: 22, 2: 30})
    assert distance == ColorDistance(0, 0, 0, 0, 0, 0)
    assert distance.as_tuple() == (0, 0, 0, 0, 0, 0)


def test_unstable_target_role_marks_profile_incomplete() -> None:
    profile = build_colorgraph_profile(
        CANDIDATE_PCDUMP,
        "f",
        0,
        {75: 2},
        required_roles={1, 2},
    )

    assert profile.complete is False
    assert profile.missing_roles == (1,)


def test_unmapped_evidence_and_duplicate_roles_are_incomplete() -> None:
    unmapped = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1})
    duplicate_without_required_roles = build_colorgraph_profile(
        CANDIDATE_PCDUMP,
        "f",
        0,
        {58: 1, 75: 1},
    )
    duplicate = build_colorgraph_profile(
        CANDIDATE_PCDUMP,
        "f",
        0,
        {58: 1, 75: 1},
        required_roles={1, 2},
    )

    assert unmapped.complete is False
    assert unmapped.missing_roles == ()
    assert duplicate_without_required_roles.complete is False
    assert duplicate_without_required_roles.missing_roles == (1,)
    assert duplicate.complete is False
    assert duplicate.missing_roles == (1, 2)


def test_distance_uses_shared_order_projection_and_symmetric_set_deltas() -> None:
    donor = ColorGraphProfile(
        assignments=((1, 9), (2, 8)),
        simplify_order=(2, 1),
        select_order=(1, 2),
        interference_edges=frozenset({(1, 2), (2, 4)}),
        coalesce_pairs=frozenset({(1, 2)}),
        spills=frozenset({2}),
        complete=True,
    )
    candidate = ColorGraphProfile(
        assignments=((1, 22), (2, 30), (3, 7)),
        simplify_order=(1, 3, 2),
        select_order=(2, 3, 1),
        interference_edges=frozenset({(1, 2), (3, 4)}),
        coalesce_pairs=frozenset({(2, 1)}),
        spills=frozenset({2, 3}),
        complete=True,
    )

    distance = colorgraph_distance(candidate, donor, desired_phys={1: 22, 2: 30})

    assert distance == ColorDistance(
        assignment_misses=0,
        simplify_order_inversions=1,
        select_order_inversions=1,
        interference_edge_delta=2,
        coalesce_delta=2,
        spill_delta=1,
    )


def test_final_matching_sections_supply_retry_state() -> None:
    retry_dump = (
        CANDIDATE_PCDUMP
        + """

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 75 1 1 0x00
1 58 1 1 0x08 SPILLED

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
iter ig_idx reg degree nIntfr flags
0 75 r30 1 1 0x00
  interferers: 58=r22
1 58 r22 1 1 0x00
  interferers: 75=r30
"""
    )

    profile = build_colorgraph_profile(retry_dump, "f", 0, {58: 1, 75: 2})

    assert profile.simplify_order == (2, 1)
    assert profile.select_order == (2, 1)
    assert profile.spills == frozenset({1})


def test_missing_function_or_decisions_is_incomplete() -> None:
    missing_function = build_colorgraph_profile(CANDIDATE_PCDUMP, "missing", 0, {}, required_roles={1})
    missing_class = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 9, {}, required_roles={2, 1})

    assert missing_function.complete is False
    assert missing_function.missing_roles == (1,)
    assert missing_class.complete is False
    assert missing_class.missing_roles == (1, 2)


def test_incomplete_profiles_cannot_be_compared() -> None:
    complete = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1, 75: 2})
    incomplete = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1})

    with pytest.raises(ValueError, match="incomplete color graph profile"):
        colorgraph_distance(incomplete, complete, desired_phys={1: 22})
    with pytest.raises(ValueError, match="incomplete color graph profile"):
        colorgraph_distance(complete, incomplete, desired_phys={1: 22})


def test_profiles_are_frozen() -> None:
    profile = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1, 75: 2})

    with pytest.raises(FrozenInstanceError):
        profile.complete = False  # type: ignore[misc]
