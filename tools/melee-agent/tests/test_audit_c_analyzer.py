"""Regression tests for confirmed bugs in src/hooks/c_analyzer.py.

Covers:
- BUG 1: detect_pointer_arithmetic must flag all 4 documented patterns,
  not just '*(f32*)((u8*)fp + 0x844)'.
- BUG 2: the byte-cast subscript branch must be whitespace-agnostic so
  '(u8 *)ptr' (clang-format spelling) is flagged like '(u8*)ptr'.

Over-correction guards are included so the widened detection cannot trivially
over-trigger on legitimate C.
"""

import pytest

from src.hooks.c_analyzer import (
    TREE_SITTER_AVAILABLE,
    analyze_diff_additions,
    detect_pointer_arithmetic,
)

pytestmark = pytest.mark.skipif(
    not TREE_SITTER_AVAILABLE, reason="tree-sitter not available"
)


def _wrap(stmt: str) -> str:
    """Wrap a statement in a trivial function so tree-sitter parses it."""
    return f"void f(void) {{ {stmt} }}"


# ---------------------------------------------------------------------------
# BUG 1: all four documented pointer-arithmetic patterns must be flagged.
# ---------------------------------------------------------------------------


def test_deref_cast_plain_base_offset_flagged():
    # Documented pattern: *(type*)(base + offset)
    issues = detect_pointer_arithmetic(_wrap("*(type*)(base + offset);"))
    assert len(issues) == 1, issues


def test_field_cast_inner_arith_flagged():
    # Documented pattern: ((Type*)(ptr + 0x10))->member
    issues = detect_pointer_arithmetic(_wrap("((Type*)(ptr + 0x10))->member;"))
    assert len(issues) == 1, issues


def test_field_binary_base_with_cast_left_flagged():
    # Documented pattern: ((u8*)ptr + offset)->field
    # Here the unwrapped base is a binary_expression, not a cast_expression.
    issues = detect_pointer_arithmetic(_wrap("((u8*)ptr + offset)->field;"))
    assert len(issues) == 1, issues


def test_deref_nested_byte_cast_still_flagged():
    # Already-working documented pattern: *(f32*)((u8*)fp + 0x844)
    issues = detect_pointer_arithmetic(_wrap("*(f32*)((u8*)fp + 0x844);"))
    assert len(issues) == 1, issues


# ---------------------------------------------------------------------------
# BUG 1 over-correction guards: legitimate code must NOT be flagged.
# ---------------------------------------------------------------------------


def test_plain_array_index_not_flagged():
    assert detect_pointer_arithmetic(_wrap("arr[i];")) == []


def test_normal_arithmetic_not_flagged():
    assert detect_pointer_arithmetic(_wrap("int z = a + b;")) == []


def test_struct_field_access_not_flagged():
    assert detect_pointer_arithmetic(_wrap("fp->x = 0;")) == []


def test_struct_field_access_dot_not_flagged():
    assert detect_pointer_arithmetic(_wrap("obj.x = 0;")) == []


# ---------------------------------------------------------------------------
# BUG 2: byte-cast subscript branch must be whitespace-agnostic.
# ---------------------------------------------------------------------------


def test_byte_cast_subscript_with_space_flagged():
    # clang-format spelling: '(u8 *)ptr' must be flagged like '(u8*)ptr'.
    issues = detect_pointer_arithmetic(_wrap("((u8 *)ptr)[0x40];"))
    assert len(issues) == 1, issues


def test_byte_cast_subscript_without_space_still_flagged():
    # Guard: the original space-less spelling must keep being flagged.
    issues = detect_pointer_arithmetic(_wrap("((u8*)ptr)[0x40];"))
    assert len(issues) == 1, issues


# ---------------------------------------------------------------------------
# End-to-end: analyze_diff_additions over a hunk adding two anti-pattern lines.
# ---------------------------------------------------------------------------


def test_analyze_diff_additions_two_antipatterns():
    diff = (
        "diff --git a/src/melee/x.c b/src/melee/x.c\n"
        "--- a/src/melee/x.c\n"
        "+++ b/src/melee/x.c\n"
        "@@ -1,2 +1,4 @@\n"
        " void f(void) {\n"
        "+    *(type*)(base + offset);\n"
        "+    ((u8 *)ptr)[0x40];\n"
        " }\n"
    )
    issues = analyze_diff_additions(diff)
    assert len(issues) == 2, issues
