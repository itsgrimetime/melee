"""Tests for the cast audit module."""

from __future__ import annotations

from src.mwcc_debug.cast_audit import (
    _looks_integer,
    _split_args,
    audit_function_casts,
    detect_signedness_mismatches,
    find_call_sites,
)


def test_split_args_top_level_commas() -> None:
    """`_split_args` should split only on top-level commas, not nested ones."""
    args = _split_args("a, b, c")
    assert args == ["a", "b", "c"]

    args = _split_args("foo(x, y), bar(z), w")
    assert args == ["foo(x, y)", "bar(z)", "w"]

    args = _split_args("(f32) i, struct[a, b], 1")
    assert args == ["(f32) i", "struct[a, b]", "1"]


def test_split_args_empty_argument_list() -> None:
    assert _split_args("") == []


def test_find_call_sites_basic() -> None:
    fn = """
{
    foo(1, 2, 3);
    bar(x, (f32) y);
}
"""
    sites = find_call_sites(fn)
    assert len(sites) == 2
    assert sites[0].call_target == "foo"
    assert len(sites[0].args) == 3
    assert sites[1].call_target == "bar"
    assert len(sites[1].args) == 2
    assert sites[1].args[1].cast_type == "f32"
    assert sites[1].args[1].inner_expr == "y"


def test_find_call_sites_skips_keywords() -> None:
    """if/while/etc. are not function calls."""
    fn = """
{
    if (x > 0) {
        foo(y);
    }
    while (a < b) {
        bar(c);
    }
}
"""
    sites = find_call_sites(fn)
    names = [s.call_target for s in sites]
    assert "if" not in names
    assert "while" not in names
    assert "foo" in names
    assert "bar" in names


def test_looks_integer_basic() -> None:
    # Integer literals
    assert _looks_integer("0")
    assert _looks_integer("-1")
    assert _looks_integer("0xFF")
    assert _looks_integer("100u")
    # Float literals — not integer
    assert not _looks_integer("0.0")
    assert not _looks_integer("0.0f")
    assert not _looks_integer("-1.5")
    # Short integer names
    assert _looks_integer("i")
    assert _looks_integer("j")
    # Names with integer suffix
    assert _looks_integer("name_idx")
    assert _looks_integer("scroll_offset")
    assert _looks_integer("retry_count")
    # Generic names — NOT classified as integer (we'd rather miss than
    # false-flag at the heuristic tier)
    assert not _looks_integer("rumble_setting")
    assert not _looks_integer("value")
    assert not _looks_integer("result")


def test_audit_function_casts_flags_f32_on_int_var() -> None:
    """The mnvibration agent's exact case: `(f32) rumble_setting`.

    The cast is on `rumble_setting`, which is declared `int` in the
    function signature. Our local-types extraction should catch this and
    classify as HIGH severity.
    """
    src = """
void example_fn(int rumble_setting)
{
    lb_80011E24(jobj, &panel_jobj, 2, -1, (f32) rumble_setting);
}
"""
    warnings = audit_function_casts(src, "example_fn")
    high = [w for w in warnings if w.severity == "high"]
    assert len(high) == 1
    assert high[0].call_target == "lb_80011E24"
    assert high[0].cast_type == "f32"
    assert high[0].inner_expr == "rumble_setting"
    assert "drop-variadic-cast" in high[0].reason


def test_audit_function_casts_medium_for_heuristic_only() -> None:
    """A cast on a value the heuristic suspects but we can't prove —
    should be MEDIUM, not HIGH."""
    src = """
void example_fn(void)
{
    bar((f32) i);  // i isn't declared anywhere visible
}
"""
    warnings = audit_function_casts(src, "example_fn")
    high = [w for w in warnings if w.severity == "high"]
    medium = [w for w in warnings if w.severity == "medium"]
    # `i` is in our loop-counter name set → medium severity flag
    assert len(high) == 0
    assert len(medium) == 1
    assert medium[0].inner_expr == "i"


def test_audit_does_not_flag_legitimate_float_cast() -> None:
    """A cast on a known float-typed value shouldn't be flagged HIGH."""
    src = """
void example_fn(double value)
{
    bar((f32) value);
}
"""
    warnings = audit_function_casts(src, "example_fn")
    # The (f32)value cast is technically an explicit cast but the value
    # name `value` doesn't match our integer-naming heuristic, so it
    # should only be LOW severity.
    high = [w for w in warnings if w.severity == "high"]
    assert len(high) == 0
    # But there should be a low-severity entry surfaced for audit.
    low = [w for w in warnings if w.severity == "low"]
    assert len(low) >= 1
    assert low[0].cast_type == "f32"


def test_audit_multiple_casts_in_one_call() -> None:
    src = """
void f(void)
{
    foo((u8) a, (s32) b, (f32) c);
}
"""
    warnings = audit_function_casts(src, "f")
    cast_types = [w.cast_type for w in warnings]
    assert "u8" in cast_types
    assert "s32" in cast_types
    assert "f32" in cast_types


def test_audit_line_numbers_correct() -> None:
    src = """// line 1
// line 2
void f(void)  // line 3
{             // line 4
    foo(1);   // line 5
    bar((f32) i);  // line 6
}
"""
    warnings = audit_function_casts(src, "f")
    # The bar call is on line 6
    bar_warnings = [w for w in warnings if w.call_target == "bar"]
    assert len(bar_warnings) == 1
    assert bar_warnings[0].line == 6


def test_audit_function_not_found() -> None:
    assert audit_function_casts("/* empty file */", "nope") == []


# ---------------------------------------------------------------------------
# Signedness mismatch detection tests
# ---------------------------------------------------------------------------

def test_detect_signedness_unsigned_vs_signed() -> None:
    """Current emits cmplwi (unsigned) but expected has cmpwi (signed)."""
    diff_lines = [
        "-/* 80245C18 002427F8  2C 0E 00 00 */\tcmpwi r14, 0x0",
        "+/* 80245C18 002427F8  28 0E 00 00 */\tcmplwi r14, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 1
    assert mismatches[0].kind == "unsigned_vs_signed"
    assert mismatches[0].current_opcode == "cmplwi"
    assert mismatches[0].expected_opcode == "cmpwi"
    assert "u8/u16/u32/unsigned" in mismatches[0].suggestion
    assert "s8/s16/s32/int" in mismatches[0].suggestion


def test_detect_signedness_signed_vs_unsigned() -> None:
    """Current emits cmpwi (signed) but expected has cmplwi (unsigned)."""
    diff_lines = [
        "-/* 80245C38 00242818  28 0F 00 00 */\tcmplwi r15, 0x0",
        "+/* 80245C38 00242818  2C 0F 00 00 */\tcmpwi r15, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 1
    assert mismatches[0].kind == "signed_vs_unsigned"
    assert mismatches[0].current_opcode == "cmpwi"
    assert mismatches[0].expected_opcode == "cmplwi"
    assert "s8/s16/s32/int" in mismatches[0].suggestion
    assert "u8/u16/u32/unsigned" in mismatches[0].suggestion


def test_detect_signedness_no_mismatch_when_both_unsigned() -> None:
    """Both sides use cmplwi — not a mismatch."""
    diff_lines = [
        "-/* 80245C38 00242818  28 0F 00 00 */\tcmplwi r15, 0x1",
        "+/* 80245C38 00242818  28 0F 00 00 */\tcmplwi r15, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 0


def test_detect_signedness_no_mismatch_when_both_signed() -> None:
    """Both sides use cmpwi — not a mismatch."""
    diff_lines = [
        "-/* 80245C18 002427F8  2C 0E 00 07 */\tcmpwi r14, 0x7",
        "+/* 80245C18 002427F8  2C 0E 00 00 */\tcmpwi r14, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 0


def test_detect_signedness_ignores_non_cmp_pairs() -> None:
    """Unrelated opcode differences are not flagged."""
    diff_lines = [
        "-\taddi r3, r4, 0x0",
        "+\tli r3, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 0


def test_detect_signedness_multiple_in_one_diff() -> None:
    """Multiple cmp mismatches in the same diff are all reported."""
    diff_lines = [
        "-/* 80245C18 002427F8  2C 0E 00 00 */\tcmpwi r14, 0x0",
        "+/* 80245C18 002427F8  28 0E 00 00 */\tcmplwi r14, 0x0",
        " /* context line */",
        "-/* 80245C38 00242818  28 0F 00 00 */\tcmplwi r15, 0x0",
        "+/* 80245C38 00242818  2C 0F 00 00 */\tcmpwi r15, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 2
    kinds = {m.kind for m in mismatches}
    assert "unsigned_vs_signed" in kinds
    assert "signed_vs_unsigned" in kinds


def test_detect_signedness_context_line_flushes_pending() -> None:
    """A context line between a '-' and '+' means no pairing."""
    diff_lines = [
        "-/* 80245C18 002427F8  2C 0E 00 00 */\tcmpwi r14, 0x0",
        " /* context line breaks the pair */",
        "+/* 80245C38 00242818  28 0F 00 00 */\tcmplwi r15, 0x0",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    # The '-' and '+' are separated by a context line, so no pairing.
    assert len(mismatches) == 0


def test_detect_signedness_cmplw_vs_cmpw() -> None:
    """Register-register form: cmplw vs cmpw (no immediate)."""
    diff_lines = [
        "-/* 80245FBC 00242B9C  7C 04 40 40 */\tcmpw r4, r8",
        "+/* 80245FBC 00242B9C  7C 04 78 40 */\tcmplw r4, r8",
    ]
    mismatches = detect_signedness_mismatches(diff_lines)
    assert len(mismatches) == 1
    assert mismatches[0].kind == "unsigned_vs_signed"
    assert mismatches[0].expected_opcode == "cmpw"
    assert mismatches[0].current_opcode == "cmplw"
