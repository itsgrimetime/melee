from __future__ import annotations

import re
import textwrap
from dataclasses import FrozenInstanceError

import pytest

from src.mwcc_debug.stack_home_profile import (
    StackHome,
    StackHomeDistance,
    StackHomeProfile,
    build_stack_home_profile,
    stack_home_distance,
)
from src.mwcc_debug.stack_slot_bridge import explain_stack_slot_localizer


def _assignment(symbol: str, offset: int, order: int, opcode: str = "stw") -> dict:
    return {
        "assignment_order": order,
        "symbol": symbol,
        "offset": offset,
        "size": 4,
        "kind": "local-or-temporary",
        "access_count": 1,
        "opcodes": [opcode],
        "first_access": {
            "opcode": opcode,
            "operands": f"r3,{symbol}(r1)",
            "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
            "block_idx": 0,
            "instr_idx": order + 1,
        },
    }


def _frame(frame_size: int | None, *assignments: dict) -> dict:
    return {
        "function": "f",
        "current": {
            "frame_size": frame_size,
            "stack_home_assignment_status": (
                "resolved-symbolic-homes" if assignments else "unavailable-no-resolved-symbolic-homes"
            ),
            "stack_home_assignments": list(assignments),
        },
    }


def _temp_candidate(
    offset: int,
    expression: str,
    *,
    opcode: str = "stfs",
    expected_offset: int | None = None,
    source_line: int = 12,
) -> dict:
    mismatch = {
        "opcode": opcode,
        "current_offset": offset,
        "expected_offset": expected_offset,
        "delta": None if expected_offset is None else expected_offset - offset,
    }
    return {
        "mismatch": mismatch,
        "opcode": opcode,
        "current_offset": offset,
        "expected_offset": expected_offset,
        "nearest_source_expression": {
            "expression": expression,
            "confidence": "pcode-first-def",
            "source_file": "src/melee/test.c",
            "source_line": source_line,
            "source_col": 9,
        },
        "evidence": [f"BEFORE REGISTER COLORING B0:3 {opcode} f50,{offset}(r1)"],
    }


def _bridge(*candidates: dict, status: str | None = None) -> dict:
    return {
        "status": status or ("ok" if candidates else "no-candidates"),
        "function": "f",
        "candidate_count": len(candidates),
        "candidates": list(candidates),
    }


def test_symbolic_homes_use_stable_assignment_identity_and_signed_offsets() -> None:
    profile = build_stack_home_profile(
        _frame(64, _assignment("saved", -8, 0), _assignment("cursor", 24, 1)),
        _bridge(),
    )

    assert profile == StackHomeProfile(
        frame_size=64,
        homes=(
            StackHome("symbol:saved", -8, 0, "proxy"),
            StackHome("symbol:cursor", 24, 1, "proxy"),
        ),
        complete=True,
    )


def test_compiler_temp_offset_is_scored_with_stable_first_def_identity() -> None:
    reference = build_stack_home_profile(
        _frame(80),
        _bridge(_temp_candidate(0x34, "fadds f70, f60, f61", expected_offset=0x34)),
    )
    candidate = build_stack_home_profile(
        _frame(80),
        _bridge(_temp_candidate(0x30, "fadds f50,f40,f41", expected_offset=0x34)),
    )

    assert candidate.homes[0].identity == reference.homes[0].identity
    assert "0x30" not in candidate.homes[0].identity
    assert "48" not in candidate.homes[0].identity
    assert stack_home_distance(candidate, reference).as_tuple() == (1, 4, 0, 0)


def test_explicit_first_def_and_unique_source_owner_are_supported() -> None:
    candidate = _temp_candidate(20, "fadds f50,f40,f41")
    candidate["first_def"] = {"opcode": "fadds", "operands": "f50,f40,f41"}

    profile = build_stack_home_profile(_frame(64), _bridge(candidate))

    assert profile.complete is True
    assert profile.homes[0].reference_kind == "proxy"


def test_anonymous_frame_assignment_uses_matching_bridge_owner() -> None:
    profile = build_stack_home_profile(
        _frame(64, _assignment("@810", 0x30, 0, "stfs")),
        _bridge(_temp_candidate(0x30, "fadds f50,f40,f41")),
    )

    assert profile.complete is True
    assert len(profile.homes) == 1
    assert profile.homes[0].identity.startswith("compiler-temp:")
    assert "@810" not in profile.homes[0].identity


def test_anonymous_frame_assignment_without_bridge_owner_is_unresolved() -> None:
    profile = build_stack_home_profile(
        _frame(64, _assignment("@810", 0x30, 0, "stfs")),
        _bridge(),
    )

    assert profile.homes == ()
    assert profile.blockers == ("unresolved-compiler-temp-home",)


def test_anonymous_frame_assignment_with_multiple_matching_owners_is_ambiguous() -> None:
    left = _temp_candidate(0x30, "fadds f50,f40,f41")
    right = _temp_candidate(0x30, "fmuls f70,f60,f61", source_line=13)
    right["evidence"] = ["BEFORE REGISTER COLORING B0:4 stfs f70,48(r1)"]

    profile = build_stack_home_profile(
        _frame(64, _assignment("@810", 0x30, 0, "stfs")),
        _bridge(left, right),
    )

    assert profile.blockers == ("ambiguous-compiler-temp-home",)
    assert all(not home.identity.startswith("symbol:@") for home in profile.homes)


def test_registers_offsets_and_temp_ids_are_removed_from_identity() -> None:
    left = _temp_candidate(48, "lwz r31,48(r1)")
    left["nearest_source_expression"]["name"] = "owner_48(r1)_r1_f1_@810"
    left["first_def"] = {"opcode": "lwz", "operands": "r50,48(r1)"}
    right = _temp_candidate(52, "lwz r31,52(r31)")
    right["nearest_source_expression"]["name"] = "owner_52(r1)_r50_f31_@910"
    right["first_def"] = {"opcode": "lwz", "operands": "r31,52(r31)"}

    left_profile = build_stack_home_profile(_frame(80), _bridge(left))
    right_profile = build_stack_home_profile(_frame(80), _bridge(right))

    assert left_profile.homes[0].identity == right_profile.homes[0].identity
    identity = left_profile.homes[0].identity
    assert re.search(r"[fr]\d+", identity, re.IGNORECASE) is None
    assert "48" not in identity
    assert "52" not in identity
    assert "@810" not in identity
    assert "@910" not in identity


def test_pcode_expression_first_def_normalizes_fpr_ids() -> None:
    left = build_stack_home_profile(
        _frame(64),
        _bridge(_temp_candidate(20, "fadds f1,f31,f50")),
    )
    right = build_stack_home_profile(
        _frame(64),
        _bridge(_temp_candidate(20, "fadds f50,f1,f31")),
    )

    assert left.homes[0].identity == right.homes[0].identity
    assert re.search(r"[fr]\d+", left.homes[0].identity, re.IGNORECASE) is None


def test_named_home_absorbs_duplicate_bridge_access_instead_of_becoming_temp() -> None:
    profile = build_stack_home_profile(
        _frame(64, _assignment("tmp", 24, 0, "stfs")),
        _bridge(_temp_candidate(24, "fadds f50,f40,f41")),
    )

    assert profile.complete is True
    assert [home.identity for home in profile.homes] == ["symbol:tmp"]


def test_unresolved_or_ambiguous_compiler_temp_is_incomplete() -> None:
    unresolved = _temp_candidate(24, "sqrtf(dx * dx + dy * dy)")
    unresolved["nearest_source_expression"]["confidence"] = "source-call-heuristic"
    unresolved["nearest_source_expression"].pop("source_line")
    unresolved["nearest_source_expression"].pop("source_col")
    ambiguous = _bridge(
        _temp_candidate(24, "fadds f50,f40,f41"),
        _temp_candidate(28, "fadds f70,f60,f61"),
    )

    unresolved_profile = build_stack_home_profile(_frame(64), _bridge(unresolved))
    ambiguous_profile = build_stack_home_profile(_frame(64), ambiguous)

    assert unresolved_profile.complete is False
    assert unresolved_profile.blockers == ("unresolved-compiler-temp-home",)
    assert ambiguous_profile.complete is False
    assert ambiguous_profile.blockers == ("ambiguous-compiler-temp-home",)


def test_heuristic_owner_is_rejected_even_with_explicit_first_def() -> None:
    candidate = _temp_candidate(24, "sqrtf(dx * dx + dy * dy)")
    candidate["nearest_source_expression"]["confidence"] = "source-call-heuristic"
    candidate["first_def"] = {"opcode": "fadds", "operands": "f50,f40,f41"}

    profile = build_stack_home_profile(_frame(64), _bridge(candidate))

    assert profile.blockers == ("unresolved-compiler-temp-home",)


@pytest.mark.parametrize("missing_key", ["source_file", "source_line", "source_col"])
def test_pcode_owner_coordinates_and_source_file_are_optional(missing_key: str) -> None:
    candidate = _temp_candidate(24, "fadds f50,f40,f41")
    candidate["nearest_source_expression"].pop(missing_key)

    profile = build_stack_home_profile(_frame(64), _bridge(candidate))

    assert profile.complete is True


def test_duplicate_pcode_owner_signature_is_ambiguous_despite_distinct_coordinates() -> None:
    left = _temp_candidate(24, "fadds f50,f40,f41")
    right = _temp_candidate(28, "fadds f70,f60,f61", source_line=99)
    right["evidence"] = ["BEFORE REGISTER COLORING B0:4 stfs f70,28(r1)"]

    profile = build_stack_home_profile(_frame(64), _bridge(left, right))

    assert profile.blockers == ("ambiguous-compiler-temp-home",)


@pytest.mark.parametrize("expression", ["", "fadds"])
def test_empty_or_malformed_pcode_expression_is_rejected(expression: str) -> None:
    candidate = _temp_candidate(24, expression)
    candidate["first_def"] = {"opcode": "fadds", "operands": "f50,f40,f41"}

    profile = build_stack_home_profile(_frame(64), _bridge(candidate))

    assert profile.blockers == ("unresolved-compiler-temp-home",)


def test_explicit_first_def_contradicting_pcode_owner_is_rejected() -> None:
    candidate = _temp_candidate(24, "fadds f50,f40,f41")
    candidate["first_def"] = {"opcode": "fmuls", "operands": "f50,f40,f41"}

    profile = build_stack_home_profile(_frame(64), _bridge(candidate))

    assert profile.blockers == ("unresolved-compiler-temp-home",)


def test_real_bridge_pcode_first_def_output_builds_anonymous_home() -> None:
    pcdump = textwrap.dedent("""\
        Starting function f
        BEFORE REGISTER COLORING
        f
        B0: Succ={} Pred={} Labels={}
            fadds   f50,f40,f41
            stfs    f50,48(r1)
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        f
        B0: Succ={} Pred={} Labels={}
            stfs    f1,48(r1)
    """)
    bridge = explain_stack_slot_localizer(
        pcdump,
        "f",
        {
            "frame_size": 64,
            "mismatch_count": 1,
            "deltas": [4],
            "mismatches": [
                {
                    "opcode": "stfs",
                    "expected_offset": 52,
                    "current_offset": 48,
                    "delta": 4,
                }
            ],
        },
    )

    owner = bridge["candidates"][0]["nearest_source_expression"]
    assert owner == {
        "expression": "fadds f50,f40,f41",
        "confidence": "pcode-first-def",
        "source_file": None,
        "source_line": None,
        "source_col": None,
    }
    profile = build_stack_home_profile(
        _frame(64, _assignment("@810", 48, 0, "stfs")),
        bridge,
    )
    assert profile.complete is True
    assert profile.homes[0].identity.startswith("compiler-temp:")
    assert "f50" not in profile.homes[0].identity
    assert "@810" not in profile.homes[0].identity


@pytest.mark.parametrize(
    ("frame_report", "slot_report", "blockers"),
    [
        (_frame(None), _bridge(), ("missing-frame-size",)),
        (
            {"function": "f", "current": {"frame_size": 64}},
            _bridge(),
            ("incomplete-frame-report",),
        ),
        (_frame(64), None, ("incomplete-stack-slot-evidence",)),
        (_frame(64), {}, ("incomplete-stack-slot-evidence",)),
        (
            _frame(64),
            {"status": "ok", "function": "f", "candidate_count": 1, "candidates": []},
            ("incomplete-stack-slot-evidence",),
        ),
        (
            _frame(64),
            {"status": "no-candidates", "candidate_count": 0, "candidates": []},
            ("incomplete-stack-slot-evidence",),
        ),
        (
            _frame(64),
            {"status": "no-candidates", "function": "other", "candidate_count": 0, "candidates": []},
            ("incomplete-stack-slot-evidence",),
        ),
    ],
)
def test_missing_or_structurally_incomplete_evidence_fails_closed(
    frame_report: dict,
    slot_report: dict | None,
    blockers: tuple[str, ...],
) -> None:
    profile = build_stack_home_profile(frame_report, slot_report)

    assert profile.complete is False
    assert profile.blockers == blockers


def test_duplicate_symbolic_identity_and_ambiguous_named_temp_collision_fail_closed() -> None:
    duplicate = build_stack_home_profile(
        _frame(64, _assignment("tmp", 20, 0), _assignment("tmp", 24, 1)),
        _bridge(),
    )
    collision = build_stack_home_profile(
        _frame(
            64,
            _assignment("left", 24, 0, "stfs"),
            _assignment("right", 24, 1, "stfs"),
        ),
        _bridge(_temp_candidate(24, "fadds f50,f40,f41")),
    )

    assert duplicate.blockers == ("duplicate-stack-home-identity",)
    assert collision.blockers == ("ambiguous-compiler-temp-home",)


def test_distance_counts_membership_moves_joined_order_and_frame_delta() -> None:
    reference = build_stack_home_profile(
        _frame(
            80,
            _assignment("alpha", 8, 0),
            _assignment("beta", 12, 1),
            _assignment("removed", 20, 2),
        ),
        _bridge(),
    )
    candidate = build_stack_home_profile(
        _frame(
            72,
            _assignment("beta", 16, 0),
            _assignment("alpha", 8, 1),
            _assignment("added", 28, 2),
        ),
        _bridge(),
    )

    assert stack_home_distance(candidate, reference) == StackHomeDistance(
        unresolved_or_mismatched_homes=3,
        total_absolute_offset_delta=4,
        home_order_inversions=1,
        absolute_frame_size_delta=8,
    )


def test_distance_rejects_incomplete_profiles() -> None:
    with pytest.raises(ValueError, match="^incomplete-stack-home-evidence$"):
        stack_home_distance(
            build_stack_home_profile(_frame(None), _bridge()),
            build_stack_home_profile(_frame(64), _bridge()),
        )


def test_public_profile_types_are_immutable() -> None:
    profile = build_stack_home_profile(_frame(64, _assignment("tmp", 24, 0)), _bridge())
    distance = stack_home_distance(profile, profile)

    with pytest.raises(FrozenInstanceError):
        profile.complete = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        profile.homes[0].offset = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        distance.absolute_frame_size_delta = 1  # type: ignore[misc]
