"""Tests for scope_path utilities."""
from __future__ import annotations

from src.mwcc_debug.scope_path import (
    format_for_display,
    is_nested_within,
    nearest_common_ancestor,
    parse_display,
)


def test_is_nested_within_same_path() -> None:
    p = ("fn", "block@l10c4")
    assert is_nested_within(p, p) is True


def test_is_nested_within_child() -> None:
    parent = ("fn",)
    child = ("fn", "block@l10c4")
    assert is_nested_within(child, parent) is True


def test_is_nested_within_sibling_returns_false() -> None:
    a = ("fn", "block@l10c4")
    b = ("fn", "block@l20c4")
    assert is_nested_within(a, b) is False


def test_is_nested_within_unrelated_function() -> None:
    a = ("fn1", "block@l10c4")
    b = ("fn2",)
    assert is_nested_within(a, b) is False


def test_nearest_common_ancestor_identical() -> None:
    p = ("fn", "block@l10c4")
    assert nearest_common_ancestor(p, p) == p


def test_nearest_common_ancestor_cousins() -> None:
    a = ("fn", "block@l10c4", "block@l12c8")
    b = ("fn", "block@l10c4", "block@l15c8")
    assert nearest_common_ancestor(a, b) == ("fn", "block@l10c4")


def test_nearest_common_ancestor_no_common() -> None:
    a = ("fn1", "block@l10c4")
    b = ("fn2", "block@l10c4")
    assert nearest_common_ancestor(a, b) == ()


def test_format_for_display_round_trip() -> None:
    p = ("fn", "block@l10c4", "block@l12c8")
    s = format_for_display(p)
    assert s == "fn/block@l10c4/block@l12c8"
    assert parse_display(s) == p


def test_format_for_display_empty() -> None:
    assert format_for_display(()) == ""
    assert parse_display("") == ()
