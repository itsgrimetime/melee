"""Tests for the mutation pattern catalog."""

from __future__ import annotations

from src.mwcc_debug.patterns import (
    PATTERNS,
    get_pattern,
    list_patterns,
    patterns_for_category,
)


def test_catalog_has_eight_named_patterns() -> None:
    """The 7 patterns from the original findings doc + the
    param-iter-ceiling ceiling pattern added in the next session.
    """
    expected = {
        "alias-split",
        "widen-u8-to-u32",
        "shrink-s32-to-u8",
        "drop-variadic-cast",
        "subexpr-extract",
        "decl-order",
        "chained-init",
        "param-iter-ceiling",
    }
    assert set(PATTERNS.keys()) == expected


def test_param_iter_ceiling_is_a_ceiling_pattern() -> None:
    """Verify the new ceiling pattern surfaces the "no fix" message."""
    p = PATTERNS["param-iter-ceiling"]
    # Title should signal ceiling
    assert "CEILING" in p.title.upper()
    # when_to_try should explicitly say not to attempt a fix
    assert "DON'T" in p.when_to_try.upper() or "no known" in p.summary.lower()
    # Mechanism should reference ig_idx
    assert "ig_idx" in p.mechanism.lower()


def test_every_pattern_has_required_fields() -> None:
    for name, p in PATTERNS.items():
        assert p.name == name
        assert p.title
        assert p.summary
        assert p.when_to_try
        assert p.example_before
        assert p.example_after
        assert p.mechanism
        # Examples shouldn't be identical (defeats the point)
        assert p.example_before != p.example_after


def test_get_pattern_returns_none_for_unknown() -> None:
    assert get_pattern("nonexistent-pattern") is None


def test_get_pattern_returns_match() -> None:
    p = get_pattern("alias-split")
    assert p is not None
    assert p.name == "alias-split"


def test_patterns_for_category_interference() -> None:
    """The interference category should map to alias-split + widen + shrink."""
    patterns = patterns_for_category("interference")
    names = {p.name for p in patterns}
    assert "alias-split" in names
    assert "widen-u8-to-u32" in names
    assert "drop-variadic-cast" in names


def test_patterns_for_category_rank() -> None:
    """The rank category should map to decl-order + alias-split + subexpr."""
    patterns = patterns_for_category("rank")
    names = {p.name for p in patterns}
    assert "decl-order" in names
    assert "alias-split" in names
    assert "subexpr-extract" in names


def test_patterns_for_category_spill() -> None:
    """The spill category should include patterns that reduce IG density."""
    patterns = patterns_for_category("spill")
    names = {p.name for p in patterns}
    assert "widen-u8-to-u32" in names
    assert "chained-init" in names


def test_list_patterns_in_catalog_order() -> None:
    """list_patterns should preserve insertion order (= original doc order
    + later additions)."""
    patterns = list_patterns()
    names = [p.name for p in patterns]
    assert names == [
        "alias-split",
        "widen-u8-to-u32",
        "shrink-s32-to-u8",
        "drop-variadic-cast",
        "subexpr-extract",
        "decl-order",
        "param-iter-ceiling",
        "chained-init",
    ]


def test_decl_order_pattern_mentions_enumerate_command() -> None:
    """decl-order should point users at our enumerate-decl-orders command."""
    p = get_pattern("decl-order")
    assert p is not None
    assert "enumerate-decl-orders" in p.when_to_try


def test_alias_split_example_shows_intermediate_assignment() -> None:
    """The alias-split example should have a separate `new_var = var` line."""
    p = get_pattern("alias-split")
    assert p is not None
    assert "new_var = var_r24" in p.example_after
    assert "new_var" not in p.example_before
