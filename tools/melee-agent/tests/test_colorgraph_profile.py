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


SINGLE_ROLE_PCDUMP = """\
Starting function f
[COALESCE] enter class=0 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  (none - no virtuals coalesced)
[COALESCE] exit class=0 n_virtuals=80 distinct_roots=80 forced=0

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 58 0 0 0x00

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
iter ig_idx reg degree nIntfr flags
0 58 r22 0 0 0x00
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


def test_final_matching_coalesce_section_supplies_retry_state() -> None:
    retry_dump = (
        CANDIDATE_PCDUMP
        + """

[COALESCE] enter class=0 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  75 -> 58
[COALESCE] exit class=0 n_virtuals=80 distinct_roots=79 forced=0
"""
    )

    profile = build_colorgraph_profile(retry_dump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(2, 1)})


def test_exact_duplicate_coalesce_rows_dedupe_without_ambiguity() -> None:
    pcdump = CANDIDATE_PCDUMP.replace("  58 -> 75\n", "  58 -> 75\n  58 -> 75\n")

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 2)})


@pytest.mark.parametrize(
    ("pcdump", "role_map"),
    [
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace("result=1", "result=0"),
            {58: 1},
            id="failed-colorgraph-result",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace("result=1, n_nodes=1", "result=1"),
            {58: 1},
            id="missing-node-count",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace("n_nodes=1", "n_nodes=2"),
            {58: 1},
            id="node-count-mismatch",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "0 58 r22 0 0 0x00",
                "1 58 r22 0 0 0x00",
            ),
            {58: 1},
            id="incoherent-decision-iteration",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "0 58 r22 0 0 0x00",
                "0 58 r22 1 1 0x00",
            ),
            {58: 1},
            id="missing-interferer-row",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "[COALESCE] exit class=0 n_virtuals=80 distinct_roots=80 forced=0\n",
                "",
            ),
            {58: 1},
            id="missing-coalesce-exit",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)\n"
                "iter ig_idx degree arraySize flags notes\n"
                "0 58 0 0 0x00\n\n",
                "",
            ),
            {58: 1},
            id="missing-simplify-section",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "[COALESCE] exit class=0 n_virtuals=80 distinct_roots=80 forced=0",
                "[COALESCE] exit class=0 n_virtuals=80 distinct_roots=80 forced=1",
            ),
            {58: 1},
            id="forced-count-mismatch",
        ),
    ],
)
def test_parser_integrity_failures_mark_profile_incomplete(
    pcdump: str,
    role_map: dict[int, int],
) -> None:
    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        role_map,
        required_roles={1},
    )

    assert profile.complete is False


def test_negative_ig_sentinels_count_as_rows_but_not_roles() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 0 0 0x00",
        "0 -1 0 0 0x00\n1 58 0 0 0x00",
    ).replace(
        "result=1, n_nodes=1)\niter ig_idx reg degree nIntfr flags\n0 58 r22 0 0 0x00",
        "result=1, n_nodes=2)\niter ig_idx reg degree nIntfr flags\n0 -1 r-1 0 0 0x00\n1 58 r22 0 0 0x00",
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {-1: 1, 58: 1},
        required_roles={1},
    )

    assert profile.complete is True
    assert profile.assignments == ((1, 22),)
    assert profile.simplify_order == (1,)
    assert profile.select_order == (1,)


def test_negative_sentinel_does_not_mask_truncated_simplify_rows() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace("0 58 0 0 0x00", "").replace(
        "0 58 r22 0 0 0x00",
        "0 -1 r-1 0 0 0x00",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {})

    assert profile.complete is False


def test_negative_sentinel_decision_still_validates_nonnegative_interferers() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace("0 58 0 0 0x00", "0 -1 0 0 0x00").replace(
        "0 58 r22 0 0 0x00",
        "0 -1 r-1 1 1 0x00\n  interferers: 99=r3",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {})

    assert profile.complete is False


def test_capped_coalesce_mapping_evidence_is_incomplete() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "  (none - no virtuals coalesced)\n",
        "  ...(capped at 256)\n",
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1},
        required_roles={1},
    )

    assert profile.complete is False


def test_conflicting_coalesce_roots_report_alias_role_incomplete() -> None:
    pcdump = """\
Starting function f
[COALESCE] enter class=0 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  58 -> 75
  58 -> 76
  58 -> 75
[COALESCE] exit class=0 n_virtuals=80 distinct_roots=78 forced=0

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 58 0 0 0x00
1 75 0 0 0x00
2 76 0 0 0x00

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
iter ig_idx reg degree nIntfr flags
0 58 r22 0 0 0x00
1 75 r30 0 0 0x00
2 76 r29 0 0 0x00
"""

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2, 76: 3})

    assert profile.complete is False
    assert profile.missing_roles == (1,)


def test_required_role_missing_from_simplify_is_reported_incomplete() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace("0 58 0 0 0x00", "0 -1 0 0 0x00")

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1},
        required_roles={1},
    )

    assert profile.complete is False
    assert profile.missing_roles == (1,)


@pytest.mark.parametrize(
    "pcdump",
    [
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "0 58 0 0 0x00",
                "0 58 0 0 0x00\n1 58 0 0 0x00",
            ),
            id="duplicate-simplify-role",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace("n_nodes=1", "n_nodes=2").replace(
                "0 58 r22 0 0 0x00",
                "0 58 r22 0 0 0x00\n1 58 r22 0 0 0x00",
            ),
            id="duplicate-select-role",
        ),
    ],
)
def test_duplicate_cross_lane_role_is_reported_incomplete(pcdump: str) -> None:
    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1},
        required_roles={1},
    )

    assert profile.complete is False
    assert profile.missing_roles == (1,)


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


def test_distance_rejects_complete_flag_that_projects_away_required_role() -> None:
    donor = ColorGraphProfile(
        assignments=((1, 22),),
        simplify_order=(),
        select_order=(1,),
        interference_edges=frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=True,
    )
    candidate = ColorGraphProfile(
        assignments=((1, 22),),
        simplify_order=(1,),
        select_order=(1,),
        interference_edges=frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=True,
    )

    with pytest.raises(ValueError, match="incomplete color graph profile"):
        colorgraph_distance(candidate, donor, desired_phys={1: 22})


def test_profiles_are_frozen() -> None:
    profile = build_colorgraph_profile(CANDIDATE_PCDUMP, "f", 0, {58: 1, 75: 2})

    with pytest.raises(FrozenInstanceError):
        profile.complete = False  # type: ignore[misc]
