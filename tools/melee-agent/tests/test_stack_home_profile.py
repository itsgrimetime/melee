from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.mwcc_debug.stack_home_profile import (
    StackHome,
    StackHomeDistance,
    StackHomeProfile,
    build_stack_home_profile,
    stack_home_distance,
)


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
        "current": {
            "frame_size": frame_size,
            "stack_home_assignment_status": (
                "resolved-symbolic-homes" if assignments else "unavailable-no-resolved-symbolic-homes"
            ),
            "stack_home_assignments": list(assignments),
        }
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
        None,
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
    candidate = _temp_candidate(20, "value + 1")
    candidate["nearest_source_expression"]["confidence"] = "source-expression"
    candidate["first_def"] = {"opcode": "fadds", "operands": "f50,f40,f41"}

    profile = build_stack_home_profile(_frame(64), _bridge(candidate))

    assert profile.complete is True
    assert profile.homes[0].reference_kind == "proxy"


def test_raw_stack_offset_is_removed_from_explicit_source_owner_identity() -> None:
    left = _temp_candidate(48, "owner from 48(r1)")
    left["nearest_source_expression"]["confidence"] = "source-expression"
    left["first_def"] = {"opcode": "lwz", "operands": "r50,48(r1)"}
    right = _temp_candidate(52, "owner from 52(r1)")
    right["nearest_source_expression"]["confidence"] = "source-expression"
    right["first_def"] = {"opcode": "lwz", "operands": "r70,52(r1)"}

    left_profile = build_stack_home_profile(_frame(80), _bridge(left))
    right_profile = build_stack_home_profile(_frame(80), _bridge(right))

    assert left_profile.homes[0].identity == right_profile.homes[0].identity
    assert "48(r1)" not in left_profile.homes[0].identity


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


@pytest.mark.parametrize(
    ("frame_report", "slot_report", "blocker"),
    [
        (_frame(None), None, "missing-frame-size"),
        ({"current": {"frame_size": 64}}, None, "incomplete-frame-report"),
        (_frame(64), {"status": "ok", "candidate_count": 1, "candidates": []}, "incomplete-stack-slot-evidence"),
    ],
)
def test_missing_or_structurally_incomplete_evidence_fails_closed(
    frame_report: dict,
    slot_report: dict | None,
    blocker: str,
) -> None:
    profile = build_stack_home_profile(frame_report, slot_report)

    assert profile.complete is False
    assert profile.blockers == (blocker,)


def test_duplicate_symbolic_identity_and_ambiguous_named_temp_collision_fail_closed() -> None:
    duplicate = build_stack_home_profile(
        _frame(64, _assignment("tmp", 20, 0), _assignment("tmp", 24, 1)),
        None,
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
        None,
    )
    candidate = build_stack_home_profile(
        _frame(
            72,
            _assignment("beta", 16, 0),
            _assignment("alpha", 8, 1),
            _assignment("added", 28, 2),
        ),
        None,
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
            build_stack_home_profile(_frame(None), None),
            build_stack_home_profile(_frame(64), None),
        )


def test_public_profile_types_are_immutable() -> None:
    profile = build_stack_home_profile(_frame(64, _assignment("tmp", 24, 0)), None)
    distance = stack_home_distance(profile, profile)

    with pytest.raises(FrozenInstanceError):
        profile.complete = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        profile.homes[0].offset = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        distance.absolute_frame_size_delta = 1  # type: ignore[misc]
