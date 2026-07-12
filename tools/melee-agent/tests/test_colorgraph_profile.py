from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

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


def _with_single_role_coalesce(
    rows: str,
    *,
    distinct_roots: int,
    forced_count: int = 0,
) -> str:
    start = SINGLE_ROLE_PCDUMP.index("[COALESCE] enter")
    end = SINGLE_ROLE_PCDUMP.index("\n\nSIMPLIFY GRAPH")
    coalesce = (
        "[COALESCE] enter class=0 n_virtuals=80\n"
        "[COALESCE] natural mappings (virt -> root):\n"
        f"{rows}"
        "[COALESCE] exit class=0 n_virtuals=80 "
        f"distinct_roots={distinct_roots} forced={forced_count}"
    )
    return SINGLE_ROLE_PCDUMP[:start] + coalesce + SINGLE_ROLE_PCDUMP[end:]


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


def test_stable_role_zero_is_complete_when_all_lanes_align() -> None:
    profile = build_colorgraph_profile(SINGLE_ROLE_PCDUMP, "f", 0, {58: 0})

    assert profile == ColorGraphProfile(
        assignments=((0, 22),),
        simplify_order=(0,),
        select_order=(0,),
        interference_edges=frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=True,
    )


@pytest.mark.parametrize(
    "pcdump",
    [
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "0 58 r22 0 0 0x00",
                "0 -1 r-1 0 0 0x00",
            ),
            id="assignment-and-select-missing",
        ),
        pytest.param(
            SINGLE_ROLE_PCDUMP.replace(
                "0 58 0 0 0x00",
                "0 -1 0 0 0x00",
            ),
            id="simplify-missing",
        ),
    ],
)
def test_stable_role_zero_lane_mismatch_is_deterministically_incomplete(
    pcdump: str,
) -> None:
    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 0})

    assert profile.complete is False
    assert profile.missing_roles == (0,)


def test_aligned_negative_stable_role_is_rejected_from_every_lane() -> None:
    profile = build_colorgraph_profile(SINGLE_ROLE_PCDUMP, "f", 0, {58: -1})

    assert profile.complete is False
    assert profile.assignments == ()
    assert profile.simplify_order == ()
    assert profile.select_order == ()
    assert profile.spills == frozenset()


def test_negative_decision_role_is_not_projected() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 r22 0 0 0x00",
        "0 75 r22 0 0 0x00",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: -1})

    assert profile.complete is False
    assert profile.assignments == ()
    assert profile.select_order == ()


def test_negative_simplify_and_spill_role_is_not_projected() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 0 0 0x00",
        "0 75 0 0 0x08 SPILLED",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: -1})

    assert profile.complete is False
    assert profile.simplify_order == ()
    assert profile.spills == frozenset()


def test_negative_interferer_role_is_not_projected() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 r22 0 0 0x00",
        "0 58 r22 1 1 0x00\n  interferers: 75=r3",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: -1})

    assert profile.complete is False
    assert profile.interference_edges == frozenset()


def test_negative_natural_coalesce_role_is_not_projected() -> None:
    pcdump = _with_single_role_coalesce("  58 -> 75\n", distinct_roots=79)

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: -1})

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


@pytest.mark.parametrize(
    ("rows", "distinct_roots"),
    [
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[75]: 75 -> 75\n",
            80,
            id="alias-old-new",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 58 -> 75\n",
            79,
            id="new-root",
        ),
    ],
)
def test_negative_forced_override_role_is_not_projected(
    rows: str,
    distinct_roots: int,
) -> None:
    pcdump = _with_single_role_coalesce(
        rows,
        distinct_roots=distinct_roots,
        forced_count=1,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: -1})

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


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


def _manual_complete_profile() -> ColorGraphProfile:
    return ColorGraphProfile(
        assignments=((1, 22), (9, 4)),
        simplify_order=(1, 9),
        select_order=(1, 9),
        interference_edges=frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=True,
    )


@pytest.mark.parametrize("profile_side", ["candidate", "donor"])
@pytest.mark.parametrize("lane", ["assignments", "simplify_order", "select_order"])
@pytest.mark.parametrize("defect", ["missing", "duplicate"])
def test_distance_rejects_non_target_lane_integrity_defects(
    profile_side: str,
    lane: str,
    defect: str,
) -> None:
    candidate = _manual_complete_profile()
    donor = _manual_complete_profile()
    intact_lane = getattr(candidate, lane)
    invalid_lane = intact_lane[:-1] if defect == "missing" else (*intact_lane, intact_lane[-1])
    if profile_side == "candidate":
        candidate = replace(candidate, **{lane: invalid_lane})
    else:
        donor = replace(donor, **{lane: invalid_lane})

    with pytest.raises(ValueError, match="incomplete color graph profile"):
        colorgraph_distance(candidate, donor, desired_phys={1: 22})


def test_distance_accepts_aligned_non_target_lane_roles() -> None:
    distance = colorgraph_distance(
        _manual_complete_profile(),
        _manual_complete_profile(),
        desired_phys={1: 22},
    )

    assert distance == ColorDistance(0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("assignments", ((-1, 22), (9, 4)), id="assignments"),
        pytest.param("simplify_order", (-1, 9), id="simplify-order"),
        pytest.param("select_order", (-1, 9), id="select-order"),
        pytest.param(
            "interference_edges",
            frozenset({(-1, 9)}),
            id="interference-left-endpoint",
        ),
        pytest.param(
            "interference_edges",
            frozenset({(1, -1)}),
            id="interference-right-endpoint",
        ),
        pytest.param(
            "coalesce_pairs",
            frozenset({(-1, 9)}),
            id="coalesce-alias-endpoint",
        ),
        pytest.param(
            "coalesce_pairs",
            frozenset({(1, -1)}),
            id="coalesce-root-endpoint",
        ),
        pytest.param("spills", frozenset({-1}), id="spills"),
    ],
)
def test_distance_rejects_negative_role_in_manual_profile(
    field: str,
    value: object,
) -> None:
    invalid = replace(_manual_complete_profile(), **{field: value})

    with pytest.raises(ValueError, match="negative stable role"):
        colorgraph_distance(invalid, _manual_complete_profile(), desired_phys={1: 22})


def test_distance_rejects_negative_desired_physical_role() -> None:
    with pytest.raises(
        ValueError,
        match="negative stable role in desired physical assignments",
    ):
        colorgraph_distance(
            _manual_complete_profile(),
            _manual_complete_profile(),
            desired_phys={-1: 22},
        )


def test_manual_profile_integrity_accepts_stable_role_zero() -> None:
    role_zero = ColorGraphProfile(
        assignments=((0, 22),),
        simplify_order=(0,),
        select_order=(0,),
        interference_edges=frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=True,
    )

    assert colorgraph_distance(role_zero, role_zero, desired_phys={0: 22}) == ColorDistance(
        0,
        0,
        0,
        0,
        0,
        0,
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


def test_independently_selected_retry_universe_mismatch_is_incomplete() -> None:
    retry_dump = (
        CANDIDATE_PCDUMP
        + """

[COALESCE] enter class=0 n_virtuals=81
[COALESCE] natural mappings (virt -> root):
  58 -> 75
[COALESCE] exit class=0 n_virtuals=81 distinct_roots=80 forced=0
"""
    )

    profile = build_colorgraph_profile(retry_dump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is False


def test_matching_selected_retry_universe_is_complete() -> None:
    retry_dump = (
        CANDIDATE_PCDUMP
        + """

[COALESCE] enter class=0 n_virtuals=81
[COALESCE] natural mappings (virt -> root):
  58 -> 75
[COALESCE] exit class=0 n_virtuals=81 distinct_roots=80 forced=0

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=81)
iter ig_idx degree arraySize flags notes
0 58 1 1 0x00
1 75 1 1 0x08 SPILLED
"""
    )

    profile = build_colorgraph_profile(retry_dump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is True


def test_zero_selected_retry_universe_is_incomplete() -> None:
    pcdump = """\
Starting function f
[COALESCE] enter class=0 n_virtuals=0
[COALESCE] natural mappings (virt -> root):
  (none - no virtuals coalesced)
[COALESCE] exit class=0 n_virtuals=0 distinct_roots=0 forced=0

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=0)
iter ig_idx degree arraySize flags notes
0 -1 0 0 0x00

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
iter ig_idx reg degree nIntfr flags
0 -1 r-1 0 0 0x00
"""

    profile = build_colorgraph_profile(pcdump, "f", 0, {})

    assert profile.complete is False


def test_exact_duplicate_coalesce_rows_dedupe_without_ambiguity() -> None:
    pcdump = CANDIDATE_PCDUMP.replace("  58 -> 75\n", "  58 -> 75\n  58 -> 75\n")

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 2)})


@pytest.mark.parametrize(
    "exit_line",
    [
        pytest.param(
            "[COALESCE] exit class=1 n_virtuals=80 distinct_roots=80 forced=0",
            id="class-mismatch",
        ),
        pytest.param(
            "[COALESCE] exit class=0 n_virtuals=79 distinct_roots=79 forced=0",
            id="virtual-count-mismatch",
        ),
    ],
)
def test_mismatched_coalesce_exit_marks_profile_incomplete(exit_line: str) -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "[COALESCE] exit class=0 n_virtuals=80 distinct_roots=80 forced=0",
        exit_line,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1})

    assert profile.complete is False


@pytest.mark.parametrize(
    "pcdump",
    [
        pytest.param(
            _with_single_role_coalesce(
                "  (none - no virtuals coalesced)\n",
                distinct_roots=79,
            ),
            id="zero-mappings",
        ),
        pytest.param(
            _with_single_role_coalesce("  58 -> 75\n", distinct_roots=80),
            id="natural-mapping",
        ),
        pytest.param(
            _with_single_role_coalesce(
                "  58 -> 75\n[FORCE_COALESCE] alias[58]: 75 -> 58\n",
                distinct_roots=79,
                forced_count=1,
            ),
            id="undo-override",
        ),
    ],
)
def test_impossible_final_distinct_root_count_is_incomplete(pcdump: str) -> None:
    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is False


@pytest.mark.parametrize(
    ("rows", "distinct_roots", "role_map"),
    [
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[70]: 70 -> 70\n",
            80,
            {58: 1},
            id="unmapped-alias",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 70 -> 58\n",
            80,
            {58: 1},
            id="unmapped-old-root",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 58 -> 70\n",
            79,
            {58: 1},
            id="unmapped-new-root",
        ),
    ],
)
def test_unmapped_forced_override_ig_is_incomplete(
    rows: str,
    distinct_roots: int,
    role_map: dict[int, int],
) -> None:
    pcdump = _with_single_role_coalesce(
        rows,
        distinct_roots=distinct_roots,
        forced_count=1,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, role_map)

    assert profile.complete is False


def test_forced_override_with_stale_old_root_is_incomplete() -> None:
    pcdump = _with_single_role_coalesce(
        "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 75 -> 58\n",
        distinct_roots=80,
        forced_count=1,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is False


def test_forced_override_can_undo_natural_mapping() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n[FORCE_COALESCE] alias[58]: 75 -> 58\n",
        distinct_roots=80,
        forced_count=1,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset()


def test_forced_override_redirects_final_mapping() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n[FORCE_COALESCE] alias[58]: 75 -> 76\n",
        distinct_roots=79,
        forced_count=1,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3},
    )

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 3)})


def test_forced_overrides_replay_in_order() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n[FORCE_COALESCE] alias[58]: 75 -> 76\n[FORCE_COALESCE] alias[58]: 76 -> 58\n",
        distinct_roots=80,
        forced_count=2,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3},
    )

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset()


def test_coalesce_chain_resolves_every_alias_to_ultimate_root() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n",
        distinct_roots=78,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3},
    )

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 3), (2, 3)})
    assert (1, 2) not in profile.coalesce_pairs


def test_branching_coalesce_aliases_share_the_ultimate_root() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  76 -> 75\n",
        distinct_roots=78,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3},
    )

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 2), (3, 2)})


def test_self_coalesce_root_terminates_without_emitting_an_alias() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 58\n",
        distinct_roots=80,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1})

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset()


def test_forced_override_is_applied_before_transitive_resolution() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n[FORCE_COALESCE] alias[75]: 76 -> 77\n",
        distinct_roots=78,
        forced_count=1,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3, 77: 4},
    )

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 4), (2, 4)})


@pytest.mark.parametrize(
    "role_map",
    [
        pytest.param({58: 1, 75: -1, 76: 3}, id="negative"),
        pytest.param({58: 1, 76: 3}, id="unmapped"),
        pytest.param({58: 1, 74: 2, 75: 2, 76: 3}, id="ambiguous"),
    ],
)
def test_invalid_intermediate_coalesce_role_blocks_predecessor_pair(
    role_map: dict[int, int],
) -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n",
        distinct_roots=78,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, role_map)

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_invalid_ultimate_coalesce_root_blocks_every_predecessor_pair() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n",
        distinct_roots=78,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 75: 2})

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_invalid_branch_node_blocks_all_predecessor_aliases() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  70 -> 75\n  75 -> 76\n",
        distinct_roots=77,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 70: 4, 75: -1, 76: 3},
    )

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


@pytest.mark.parametrize(
    ("rows", "distinct_roots", "role_map"),
    [
        pytest.param(
            "  70 -> 58\n[FORCE_COALESCE] alias[58]: 58 -> 76\n",
            78,
            {58: -1, 70: 4, 76: 3},
            id="alias",
        ),
        pytest.param(
            "  58 -> 75\n[FORCE_COALESCE] alias[58]: 75 -> 76\n",
            79,
            {58: 1, 75: -1, 76: 3},
            id="old-root",
        ),
        pytest.param(
            "  58 -> 75\n  76 -> 77\n[FORCE_COALESCE] alias[58]: 75 -> 76\n",
            78,
            {58: 1, 75: 2, 76: -1, 77: 4},
            id="new-root",
        ),
    ],
)
def test_invalid_forced_endpoint_blocks_redirected_component(
    rows: str,
    distinct_roots: int,
    role_map: dict[int, int],
) -> None:
    pcdump = _with_single_role_coalesce(
        rows,
        distinct_roots=distinct_roots,
        forced_count=1,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, role_map)

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_invalid_coalesce_component_retains_only_separate_valid_component() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n  70 -> 71\n",
        distinct_roots=77,
    )
    role_map = {58: 1, 70: 4, 71: 5, 75: -1, 76: 3}

    first = build_colorgraph_profile(pcdump, "f", 0, role_map)
    second = build_colorgraph_profile(pcdump, "f", 0, role_map)

    assert first == second
    assert first.complete is False
    assert first.coalesce_pairs == frozenset({(4, 5)})


@pytest.mark.parametrize(
    ("rows", "distinct_roots"),
    [
        pytest.param("  58 -> 75\n  75 -> 58\n", 78, id="two-node"),
        pytest.param(
            "  58 -> 75\n  75 -> 76\n  76 -> 58\n",
            77,
            id="three-node",
        ),
    ],
)
def test_coalesce_cycle_is_incomplete_without_stale_pairs(
    rows: str,
    distinct_roots: int,
) -> None:
    pcdump = _with_single_role_coalesce(rows, distinct_roots=distinct_roots)

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3},
    )

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_alias_leading_to_conflicting_roots_emits_no_stale_pair() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n  75 -> 77\n",
        distinct_roots=77,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3, 77: 4},
    )

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_alias_leading_to_out_of_range_mapping_emits_no_stale_pair() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 80\n",
        distinct_roots=78,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 80: 3},
    )

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_stale_forced_override_blocks_affected_alias_component() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n[FORCE_COALESCE] alias[75]: 77 -> 78\n",
        distinct_roots=78,
        forced_count=1,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3, 77: 4, 78: 5},
    )

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_transitive_root_cardinality_must_match_exactly() -> None:
    pcdump = _with_single_role_coalesce(
        "  58 -> 75\n  75 -> 76\n",
        distinct_roots=79,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 2, 76: 3},
    )

    assert profile.complete is False


def test_ambiguous_forced_override_ig_is_incomplete() -> None:
    pcdump = _with_single_role_coalesce(
        "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[70]: 70 -> 70\n",
        distinct_roots=80,
        forced_count=1,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 70: 2, 71: 2},
    )

    assert profile.complete is False
    assert profile.missing_roles == (2,)


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param("  80 -> 58\n", id="natural-alias"),
        pytest.param("  58 -> 80\n", id="natural-root"),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[80]: 80 -> 80\n",
            id="forced-alias-old-new",
        ),
    ],
)
def test_out_of_range_coalesce_ig_is_incomplete(rows: str) -> None:
    forced_count = int("FORCE_COALESCE" in rows)
    pcdump = _with_single_role_coalesce(
        rows,
        distinct_roots=80,
        forced_count=forced_count,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 80: 2})

    assert profile.complete is False


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param("  -1 -> 58\n", id="natural-alias"),
        pytest.param("  58 -> -1\n", id="natural-root"),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[-1]: 58 -> 58\n",
            id="forced-alias",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: -1 -> 58\n",
            id="forced-old-root",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 58 -> -1\n",
            id="forced-new-root",
        ),
    ],
)
def test_negative_raw_coalesce_endpoint_is_incomplete(rows: str) -> None:
    forced_count = int("FORCE_COALESCE" in rows)
    pcdump = _with_single_role_coalesce(
        rows,
        distinct_roots=80,
        forced_count=forced_count,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1})

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


def test_out_of_range_natural_mapping_is_not_role_projected() -> None:
    pcdump = _with_single_role_coalesce(
        "  80 -> 58\n",
        distinct_roots=80,
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 80: 2})

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[80]: 80 -> 58\n",
            id="alias",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 80 -> 75\n",
            id="old-root",
        ),
        pytest.param(
            "  (none - no virtuals coalesced)\n[FORCE_COALESCE] alias[58]: 58 -> 80\n",
            id="new-root",
        ),
    ],
)
def test_out_of_range_forced_override_is_not_role_projected(rows: str) -> None:
    pcdump = _with_single_role_coalesce(
        rows,
        distinct_roots=79,
        forced_count=1,
    )

    profile = build_colorgraph_profile(
        pcdump,
        "f",
        0,
        {58: 1, 75: 3, 80: 2},
    )

    assert profile.complete is False
    assert profile.coalesce_pairs == frozenset()


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
            SINGLE_ROLE_PCDUMP.replace("n_nodes=1", "n_nodes=0"),
            {58: 1},
            id="node-count-smaller-than-emitted-decisions",
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


def test_total_graph_node_count_may_exceed_emitted_virtual_decisions() -> None:
    profile = build_colorgraph_profile(
        SINGLE_ROLE_PCDUMP.replace("n_nodes=1", "n_nodes=80"),
        "f",
        0,
        {58: 1},
        required_roles={1},
    )

    assert profile.complete is True


def test_positive_simplify_only_role_is_reported_incomplete() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 r22 0 0 0x00",
        "0 -1 r-1 0 0 0x00",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1})

    assert profile.complete is False
    assert profile.missing_roles == (1,)


def test_out_of_range_decision_is_not_role_projected() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 r22 0 0 0x00",
        "0 80 r22 0 0 0x00",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 80: 2})

    assert profile.complete is False
    assert profile.assignments == ()
    assert profile.select_order == ()


def test_out_of_range_interferer_is_not_role_projected() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 r22 0 0 0x00",
        "0 58 r22 1 1 0x00\n  interferers: 80=r3",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 80: 2})

    assert profile.complete is False
    assert profile.interference_edges == frozenset()


def test_out_of_range_simplify_entry_is_not_role_projected() -> None:
    pcdump = SINGLE_ROLE_PCDUMP.replace(
        "0 58 0 0 0x00",
        "0 80 0 0 0x00",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 80: 2})

    assert profile.complete is False
    assert profile.simplify_order == ()


def test_maximum_in_range_ig_is_valid_in_every_evidence_lane() -> None:
    pcdump = CANDIDATE_PCDUMP.replace("75", "79").replace(
        "  58 -> 79\n[COALESCE] exit class=0 n_virtuals=80 distinct_roots=79 forced=0",
        "  58 -> 79\n"
        "  79 -> 79\n"
        "[FORCE_COALESCE] alias[79]: 79 -> 79\n"
        "[COALESCE] exit class=0 n_virtuals=80 distinct_roots=79 forced=1",
    )

    profile = build_colorgraph_profile(pcdump, "f", 0, {58: 1, 79: 2})

    assert profile.complete is True
    assert profile.coalesce_pairs == frozenset({(1, 2)})


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
