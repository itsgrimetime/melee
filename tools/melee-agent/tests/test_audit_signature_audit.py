"""Regression tests for signature_audit param-type parsing and call matching.

Covers audit bugs:
- BUG 12: _extract_param_types eats a type word from UNNAMED multi-word types.
- BUG 11: _split_param_type_name splits unnamed multi-word types into type+name
  and the prototype patch builder emits invalid C (e.g. ``s8 long``).
- BUG 13: _simple_call_assignment greedily matches a compound RHS where the call
  is not the complete right-hand side.
"""

from __future__ import annotations

from src.mwcc_debug.signature_audit import (
    _parse_visible_prototypes,
    _simple_call_assignment,
    _split_param_type_name,
    audit_signature_call_type,
)


def _payload(target_asm: list[str], current_asm: list[str]) -> dict:
    return {
        "function": "caller_fn",
        "classification": {"primary": "signature-type-mismatch"},
        "target_asm": target_asm,
        "current_asm": current_asm,
        "diff": [],
        "fuzzy_match_percent": 97.5,
    }


# --------------------------------------------------------------------------- #
# BUG 12: UNNAMED multi-word parameter types must keep all their words.
# --------------------------------------------------------------------------- #


def test_bug12_unnamed_unsigned_char_keeps_both_words() -> None:
    protos = _parse_visible_prototypes("int f(unsigned char);")
    assert protos["f"].param_types == ("unsigned char",)


def test_bug12_unnamed_unsigned_int_keeps_both_words() -> None:
    protos = _parse_visible_prototypes("int g(unsigned int);")
    assert protos["g"].param_types == ("unsigned int",)


def test_bug12_unnamed_long_long_keeps_both_words() -> None:
    protos = _parse_visible_prototypes("int h(long long);")
    assert protos["h"].param_types == ("long long",)


# Over-correction guards: NAMED parameters must still strip the trailing name.


def test_bug12_named_unsigned_char_strips_name() -> None:
    protos = _parse_visible_prototypes("void f(unsigned char c);")
    assert protos["f"].param_types == ("unsigned char",)


def test_bug12_named_int_strips_name() -> None:
    protos = _parse_visible_prototypes("void f(int x);")
    assert protos["f"].param_types == ("int",)


def test_bug12_named_pointer_param_unchanged() -> None:
    # Parity with the existing passing suite: named pointer params keep
    # the collapsed ``Type*`` form.
    protos = _parse_visible_prototypes("void f(HSD_GObj* g);")
    assert protos["f"].param_types == ("HSD_GObj*",)


def test_bug12_named_long_long_strips_name() -> None:
    protos = _parse_visible_prototypes("void f(long long x);")
    assert protos["f"].param_types == ("long long",)


# --------------------------------------------------------------------------- #
# BUG 11: _split_param_type_name must not split unnamed multi-word types.
# --------------------------------------------------------------------------- #


def test_bug11_split_unnamed_long_long_is_none() -> None:
    assert _split_param_type_name("long long") is None


def test_bug11_split_unnamed_unsigned_char_is_none() -> None:
    assert _split_param_type_name("unsigned char") is None


def test_bug11_split_unnamed_simple_scalar_is_none() -> None:
    assert _split_param_type_name("int") is None


# Over-correction guards: NAMED params must still split correctly.


def test_bug11_split_named_long_long() -> None:
    assert _split_param_type_name("long long x") == ("long long", "x")


def test_bug11_split_named_int() -> None:
    assert _split_param_type_name("int value") == ("int", "value")


def test_bug11_split_named_unsigned_char() -> None:
    assert _split_param_type_name("unsigned char c") == ("unsigned char", "c")


def test_bug11_unnamed_prototype_patch_is_not_corrupt_c() -> None:
    # Mirror test_audit_generates_same_tu_static_width_prototype_patch but with
    # an UNNAMED parameter; the prototype patch must NOT be invalid C such as
    # ``s8 long``.
    source = """
static void helper(long long) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    finding = report.findings[0]
    action = finding.actions[0]
    if action.patch is not None:
        # If a patch is generated for the unnamed scalar param it must be a
        # bare type, never ``<type> long`` / any corrupt multi-word form.
        assert action.patch.new == "s8"
        assert "long" not in action.patch.new
    else:
        # Acceptable alternative: declined as unsupported rather than corrupt.
        assert action.patch is None


# --------------------------------------------------------------------------- #
# BUG 13: _simple_call_assignment must only match a COMPLETE call RHS.
# --------------------------------------------------------------------------- #


def test_bug13_compound_rhs_is_rejected() -> None:
    assert (
        _simple_call_assignment("x = helper(idx) + other(idx);", 1, "helper")
        is None
    )


def test_bug13_trailing_arithmetic_after_call_is_rejected() -> None:
    assert (
        _simple_call_assignment("x = helper(idx) * 2;", 1, "helper") is None
    )


# Over-correction guards: legitimate complete-call RHS must still match,
# including nested parentheses in the argument list.


def test_bug13_simple_call_assignment_accepted() -> None:
    assert _simple_call_assignment("x = helper(idx);", 1, "helper") == (
        "x",
        "helper(idx)",
    )


def test_bug13_nested_paren_call_assignment_accepted() -> None:
    assert _simple_call_assignment("x = helper(a, g(b));", 1, "helper") == (
        "x",
        "helper(a, g(b))",
    )
