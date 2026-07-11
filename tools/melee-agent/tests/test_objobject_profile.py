"""Tests for semantic ObjObject identities and order distance."""

from __future__ import annotations

import pytest

from src.mwcc_debug.objobject_profile import (
    ObjObjectIdentity,
    objobject_order_distance,
    parse_objobject_profile,
)


def _inspect(*records: str, function: str = "f", header: str = "OBJOBJECTS") -> str:
    body = "\n".join(records)
    return f"FUNCTION: {function}\n{header}\n{body}"


def _record(
    address: str,
    name: str,
    expression: str,
    *,
    kind: str = "DLOCAL",
    type_name: str = "int",
    scope: str = "f",
    occurrence: str | None = None,
) -> str:
    occurrence_line = f"\n  Occurrence: {occurrence}" if occurrence is not None else ""
    return (
        f"ObjObject @ {address}\n"
        f"  Kind: {kind}\n"
        f"  Name: {name}\n"
        f"  Type: {type_name}\n"
        f"  Scope: {scope}\n"
        f"  Expression: {expression}{occurrence_line}"
    )


INSPECT_A = _inspect(
    _record("0x00FEC898", "alpha", "alpha + @1862"),
    _record("00FC5878", "beta", "temp_r3_15(beta)"),
)
INSPECT_SAME_OBJECTS_NEW_ADDRESSES = _inspect(
    _record("0x7FFDEADBEEF", "alpha", "alpha+@9001"),
    _record("DEADC0DEh", "beta", "temp_r29_2 ( beta )"),
)
INSPECT_REORDERED = _inspect(
    _record("0xAA10", "beta", "temp_r8_4(beta)"),
    _record("0xAA20", "alpha", "alpha + @77"),
)
INSPECT_AMBIGUOUS_DUPLICATES = _inspect(
    _record("0x10", "copy", "copy"),
    _record("0x20", "copy", "copy"),
)


def test_addresses_do_not_change_identity_or_order() -> None:
    a = parse_objobject_profile(INSPECT_A, "f")
    b = parse_objobject_profile(INSPECT_SAME_OBJECTS_NEW_ADDRESSES, "f")

    assert objobject_order_distance(a, b) == (0, 0)


def test_reordered_unique_objects_count_inversions() -> None:
    assert objobject_order_distance(
        parse_objobject_profile(INSPECT_A, "f"),
        parse_objobject_profile(INSPECT_REORDERED, "f"),
    ) == (0, 1)


def test_indistinguishable_repeated_objects_are_incomplete() -> None:
    profile = parse_objobject_profile(INSPECT_AMBIGUOUS_DUPLICATES, "f")

    assert profile.complete is False
    assert profile.blocker == "ambiguous-objobject-identity"


def test_selects_exact_functions_final_objobject_snapshot() -> None:
    text = """
FUNCTION: ff
OBJOBJECTS
ObjObject @ 0x01
  Kind: DLOCAL
  Name: wrong-function
  Type: int
  Scope: ff
  Expression: wrong-function
FUNCTION: f
OBJOBJECTS
ObjObject @ 0x02
  Kind: DLOCAL
  Name: stale
  Type: int
  Scope: f
  Expression: stale
STATEMENTS
  stale = 1
Frontend: OBJOBJECTS
ObjObject @ 0x03
  Kind: DLOCAL
  Name: final
  Type: int
  Scope: f
  Expression: final
FUNCTION: later
OBJOBJECTS
ObjObject @ 0x04
  Kind: DLOCAL
  Name: wrong-later
  Type: int
  Scope: later
  Expression: wrong-later
""".strip()

    profile = parse_objobject_profile(text, "f")

    assert profile.complete is True
    assert [identity.source_name for identity in profile.identities] == ["final"]


def test_labeled_fields_are_preserved_while_unstable_tokens_are_normalized() -> None:
    profile = parse_objobject_profile(
        _inspect(
            _record(
                "0X00ABCDEF",
                " named value ",
                "  temp_r31_4  +  @982  +  named value  ",
                kind=" DLOCAL ",
                type_name=" struct   Pair * ",
                scope=" inline::helper ",
            )
        ),
        "f",
    )

    assert profile.identities == (
        ObjObjectIdentity(
            kind="DLOCAL",
            source_name="named value",
            type_name="struct Pair*",
            scope="inline::helper",
            expression="<temp> + <temp> + named value",
        ),
    )


def test_occurrence_evidence_disambiguates_duplicate_order() -> None:
    candidate = _inspect(
        _record("0x10", "copy", "copy", occurrence="source:10"),
        _record("0x20", "copy", "copy", occurrence="source:20"),
    )
    donor = _inspect(
        _record("0x99", "copy", "copy", occurrence="source:20"),
        _record("0x88", "copy", "copy", occurrence="source:10"),
    )

    assert objobject_order_distance(
        parse_objobject_profile(candidate, "f"),
        parse_objobject_profile(donor, "f"),
    ) == (0, 1)


def test_membership_is_multiset_missing_plus_extra_before_common_order() -> None:
    alpha = _record("0x10", "alpha", "alpha")
    beta = _record("0x20", "beta", "beta")
    gamma = _record("0x30", "gamma", "gamma")

    assert objobject_order_distance(
        parse_objobject_profile(_inspect(alpha, gamma), "f"),
        parse_objobject_profile(_inspect(beta, alpha), "f"),
    ) == (2, 0)


@pytest.mark.parametrize(
    ("text", "blocker"),
    [
        ("FUNCTION: f\nSTATEMENTS\n  return", "missing-objobject-snapshot"),
        (
            _inspect("ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: truncated"),
            "incomplete-objobject-entry",
        ),
    ],
)
def test_absent_or_truncated_sections_are_incomplete(text: str, blocker: str) -> None:
    profile = parse_objobject_profile(text, "f")

    assert profile.complete is False
    assert profile.blocker == blocker


def test_distance_rejects_incomplete_profiles() -> None:
    incomplete = parse_objobject_profile("FUNCTION: f\nSTATEMENTS\n  return", "f")

    with pytest.raises(ValueError, match="^incomplete-objobject-evidence$"):
        objobject_order_distance(incomplete, parse_objobject_profile(INSPECT_A, "f"))


def test_real_inspector_single_line_form_is_supported() -> None:
    text = """
FUNCTION: f
OBJOBJECTS
  -> ObjObject @ 0x00FEC898: header (DataType: DLOCAL, Type: struct HSD_JObj*)
""".strip()

    profile = parse_objobject_profile(text, "f")

    assert profile.identities == (
        ObjObjectIdentity(
            kind="DLOCAL",
            source_name="header",
            type_name="struct HSD_JObj*",
            scope="f",
            expression="header",
        ),
    )
    assert profile.complete is True


def test_inline_labeled_record_keeps_occurrence_as_pairing_evidence() -> None:
    text = """
FUNCTION: f
OBJOBJECTS
ObjObject @ 0x10: Kind: DLOCAL; Name: copy; Type: int; Scope: f; Expression: copy; Occurrence: left
ObjObject @ 0x20: Kind: DLOCAL; Name: copy; Type: int; Scope: f; Expression: copy; Occurrence: right
""".strip()

    profile = parse_objobject_profile(text, "f")

    assert profile.complete is True
    assert len(profile.identities) == 2
