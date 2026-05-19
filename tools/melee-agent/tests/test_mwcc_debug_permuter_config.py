"""Tests for the decomp-permuter settings.toml renderer."""

from __future__ import annotations

import textwrap

import pytest
import toml

from src.mwcc_debug.patterns import PATTERNS, MutationPattern
from src.mwcc_debug.permuter_config import (
    DEFAULT_OBJDUMP_COMMAND,
    PatternSkippedError,
    SettingsTomlSpec,
    build_spec,
    parse_existing_overrides,
    render_settings_toml,
)


def test_build_spec_with_pattern_uses_pattern_weights() -> None:
    pattern = PATTERNS["decl-order"]
    spec = build_spec("fn_test", pattern)
    assert spec.func_name == "fn_test"
    assert spec.compiler_type == "mwcc"
    assert spec.pattern_name == "decl-order"
    assert spec.weight_overrides == pattern.permuter_weights


def test_build_spec_with_no_pattern_emits_empty_overrides() -> None:
    spec = build_spec("fn_test", None)
    assert spec.pattern_name is None
    assert spec.weight_overrides == {}


def test_build_spec_raises_for_skip_pattern_without_force() -> None:
    pattern = PATTERNS["param-iter-ceiling"]
    assert pattern.permuter_skip is True
    with pytest.raises(PatternSkippedError):
        build_spec("fn_test", pattern)


def test_build_spec_force_overrides_skip() -> None:
    pattern = PATTERNS["param-iter-ceiling"]
    spec = build_spec("fn_test", pattern, force=True)
    # Empty weights since param-iter-ceiling has no useful permuter
    # overrides — but the spec still builds.
    assert spec.weight_overrides == {}


def test_build_spec_merge_preserves_existing_keys() -> None:
    pattern = PATTERNS["decl-order"]  # adds reorder_decls, temp_for_expr, ins_block
    existing = {
        "perm_xor_zero": 5.0,           # not in pattern profile
        "perm_temp_for_expr": 999.0,    # in pattern profile (pattern should win)
    }
    spec = build_spec(
        "fn_test", pattern, existing_overrides=existing, merge=True
    )
    # Pattern keys win
    assert spec.weight_overrides["perm_reorder_decls"] == \
        pattern.permuter_weights["perm_reorder_decls"]
    assert spec.weight_overrides["perm_temp_for_expr"] == \
        pattern.permuter_weights["perm_temp_for_expr"]
    # Existing keys not in pattern are preserved
    assert spec.weight_overrides["perm_xor_zero"] == 5.0


def test_build_spec_no_merge_drops_existing() -> None:
    pattern = PATTERNS["decl-order"]
    existing = {"perm_xor_zero": 5.0}
    spec = build_spec(
        "fn_test", pattern, existing_overrides=existing, merge=False
    )
    # Existing keys are dropped
    assert "perm_xor_zero" not in spec.weight_overrides
    # Pattern keys are present
    assert "perm_reorder_decls" in spec.weight_overrides


def test_render_with_weights_parses_back_via_toml() -> None:
    pattern = PATTERNS["alias-split"]
    spec = build_spec("fn_xyz", pattern)
    text = render_settings_toml(spec)
    # Header comment present
    assert "# Pattern: alias-split" in text
    # Parses cleanly as TOML
    parsed = toml.loads(text)
    assert parsed["func_name"] == "fn_xyz"
    assert parsed["compiler_type"] == "mwcc"
    assert parsed["objdump_command"] == DEFAULT_OBJDUMP_COMMAND
    assert parsed["weight_overrides"]["perm_temp_for_expr"] == 60.0
    assert parsed["weight_overrides"]["perm_refer_to_var"] == 30.0


def test_render_without_weights_omits_section() -> None:
    spec = build_spec("fn_empty", None)
    text = render_settings_toml(spec)
    parsed = toml.loads(text)
    assert parsed["func_name"] == "fn_empty"
    # When there are no overrides, the section is omitted entirely
    assert "weight_overrides" not in parsed
    assert "[weight_overrides]" not in text


def test_render_sorts_keys_for_stable_diffs() -> None:
    pattern = PATTERNS["decl-order"]
    spec = build_spec("fn_sort", pattern)
    text = render_settings_toml(spec)
    # The keys in [weight_overrides] should appear in alphabetical order
    # so regenerations produce stable diffs.
    lines = [l for l in text.splitlines() if l.startswith("perm_")]
    assert lines == sorted(lines)


def test_parse_existing_overrides_extracts_keys_and_values() -> None:
    text = textwrap.dedent("""\
        func_name = "fn_test"
        compiler_type = "mwcc"

        [weight_overrides]
        # comment
        perm_reorder_decls = 50.0
        perm_temp_for_expr = 30.0
        perm_other = 1.5  # inline comment
    """)
    overrides = parse_existing_overrides(text)
    assert overrides == {
        "perm_reorder_decls": 50.0,
        "perm_temp_for_expr": 30.0,
        "perm_other": 1.5,
    }


def test_parse_existing_overrides_returns_empty_when_section_missing() -> None:
    text = 'func_name = "x"\ncompiler_type = "mwcc"\n'
    assert parse_existing_overrides(text) == {}


def test_parse_existing_overrides_handles_no_section_at_eof() -> None:
    """Section at end of file (no trailing section) still parses."""
    text = textwrap.dedent("""\
        func_name = "fn_test"

        [weight_overrides]
        perm_foo = 10.0
        perm_bar = 20.0
    """)
    assert parse_existing_overrides(text) == {
        "perm_foo": 10.0,
        "perm_bar": 20.0,
    }


def test_all_patterns_have_either_weights_or_skip() -> None:
    """Sanity: every pattern in the catalog either has non-empty
    permuter_weights or has permuter_skip=True. A pattern with
    empty weights and skip=False would generate a useless config."""
    for name, pattern in PATTERNS.items():
        if pattern.permuter_skip:
            continue  # skip is allowed even with empty weights
        assert pattern.permuter_weights, (
            f"Pattern {name!r} has empty permuter_weights and "
            f"permuter_skip=False. Add weights or set skip."
        )


def test_all_pattern_weight_keys_look_like_permuter_names() -> None:
    """Sanity: weight keys should match decomp-permuter's `perm_*`
    mutation names. Catches typos like `pem_reorder_decls`."""
    for name, pattern in PATTERNS.items():
        for key in pattern.permuter_weights:
            assert key.startswith("perm_"), (
                f"Pattern {name!r} has weight key {key!r} that doesn't "
                f"start with 'perm_'. Check default_weights.toml for the "
                f"correct mutation name."
            )
