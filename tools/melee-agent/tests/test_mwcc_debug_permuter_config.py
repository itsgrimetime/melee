"""Tests for the decomp-permuter settings.toml renderer."""

from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

import pytest

from src.mwcc_debug.patterns import PATTERNS, MutationPattern
from src.mwcc_debug.permuter_config import (
    DEFAULT_OBJDUMP_COMMAND,
    PatternSkippedError,
    ScorerConfig,
    SettingsTomlSpec,
    WEIGHT_OVERRIDE_CAPS,
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


def test_build_spec_caps_risky_internal_type_pattern_weight() -> None:
    pattern = PATTERNS["widen-u8-to-u32"]
    assert pattern.permuter_weights["perm_randomize_internal_type"] == 50.0

    spec = build_spec("fn_test", pattern)

    assert (
        spec.weight_overrides["perm_randomize_internal_type"]
        == WEIGHT_OVERRIDE_CAPS["perm_randomize_internal_type"]
    )
    assert spec.weight_overrides["perm_cast_simple"] == 30.0


def test_build_spec_caps_existing_internal_type_weight_when_merging() -> None:
    pattern = PATTERNS["alias-split"]
    spec = build_spec(
        "fn_test",
        pattern,
        existing_overrides={"perm_randomize_internal_type": 50.0},
        merge=True,
    )

    assert (
        spec.weight_overrides["perm_randomize_internal_type"]
        == WEIGHT_OVERRIDE_CAPS["perm_randomize_internal_type"]
    )
    assert spec.weight_overrides["perm_temp_for_expr"] == 60.0


def test_render_with_weights_parses_back_via_toml() -> None:
    pattern = PATTERNS["alias-split"]
    spec = build_spec("fn_xyz", pattern)
    text = render_settings_toml(spec)
    # Header comment present
    assert "# Pattern: alias-split" in text
    # Parses cleanly as TOML
    parsed = tomllib.loads(text)
    assert parsed["func_name"] == "fn_xyz"
    assert parsed["compiler_type"] == "mwcc"
    assert parsed["objdump_command"] == DEFAULT_OBJDUMP_COMMAND
    assert parsed["objdump_command"] == "melee-agent debug target dtk-objdump"
    assert parsed["weight_overrides"]["perm_temp_for_expr"] == 60.0
    assert parsed["weight_overrides"]["perm_refer_to_var"] == 30.0


def test_render_without_weights_omits_section() -> None:
    spec = build_spec("fn_empty", None)
    text = render_settings_toml(spec)
    parsed = tomllib.loads(text)
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


# ---------------------------------------------------------------------------
# [scorer] section rendering tests
# ---------------------------------------------------------------------------


def test_build_spec_without_scorer_omits_section() -> None:
    spec = build_spec("fn_test", None)
    assert spec.scorer is None
    text = render_settings_toml(spec)
    assert "[scorer]" not in text
    # Parses cleanly
    parsed = tomllib.loads(text)
    assert "scorer" not in parsed


def test_build_spec_with_scorer_attaches_config() -> None:
    sc = ScorerConfig(
        command="/path/to/score-cmd -f fn -t spec.yaml",
        timeout_seconds=10.0,
    )
    spec = build_spec("fn_test", None, scorer=sc)
    assert spec.scorer is sc


def test_render_with_scorer_emits_section() -> None:
    sc = ScorerConfig(
        command="melee-agent debug target score-simplify-order -f fn -t spec.yaml",
        timeout_seconds=7.5,
    )
    spec = build_spec("fn_test", None, scorer=sc)
    text = render_settings_toml(spec)
    assert "[scorer]" in text
    parsed = tomllib.loads(text)
    assert (
        parsed["scorer"]["command"]
        == "melee-agent debug target score-simplify-order -f fn -t spec.yaml"
    )
    assert parsed["scorer"]["timeout_seconds"] == 7.5


def test_render_scorer_default_timeout() -> None:
    sc = ScorerConfig(command="/bin/true")
    spec = build_spec("fn_test", None, scorer=sc)
    text = render_settings_toml(spec)
    parsed = tomllib.loads(text)
    assert parsed["scorer"]["timeout_seconds"] == 5.0


def test_render_scorer_with_quotes_in_command_is_escaped() -> None:
    sc = ScorerConfig(
        command='/path/to/cmd -msg "hello world"',
    )
    spec = build_spec("fn_test", None, scorer=sc)
    text = render_settings_toml(spec)
    parsed = tomllib.loads(text)
    # Round-trip through toml: the escaped quotes survive
    assert parsed["scorer"]["command"] == '/path/to/cmd -msg "hello world"'


def test_render_scorer_section_appears_after_weight_overrides() -> None:
    """Ordering matters: weight_overrides first, then [scorer]. Predictable
    layout makes diffs easier to read."""
    sc = ScorerConfig(command="/bin/true")
    pattern = PATTERNS["decl-order"]
    spec = build_spec("fn_test", pattern, scorer=sc)
    text = render_settings_toml(spec)
    wo_idx = text.index("[weight_overrides]")
    sc_idx = text.index("[scorer]")
    assert wo_idx < sc_idx


# ---------------------------------------------------------------------------
# render_simplify_order_target_yaml tests (force_phys)
# ---------------------------------------------------------------------------


def test_render_target_yaml_without_force_phys(tmp_path: Path) -> None:
    """Backward compat: target.yaml without force_phys still renders cleanly."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml

    yaml_text = render_simplify_order_target_yaml(
        function="gm_test",
        simplify_order_target=(34, 37, 32),
        class_id=0,
        baseline_dump=tmp_path / "base.txt",
        force_phys=None,
    )
    assert "function: gm_test" in yaml_text
    assert "simplify_order_target:" in yaml_text
    assert "force_phys" not in yaml_text


def test_render_target_yaml_with_force_phys(tmp_path: Path) -> None:
    """force_phys renders as a YAML mapping of int keys to int values."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml

    yaml_text = render_simplify_order_target_yaml(
        function="lbDvd_test",
        simplify_order_target=(46, 44),
        class_id=0,
        baseline_dump=tmp_path / "base.txt",
        force_phys={44: 10, 46: 12},
    )
    assert "force_phys:" in yaml_text
    assert "44: 10" in yaml_text
    assert "46: 12" in yaml_text


def test_render_target_yaml_roundtrip_with_force_phys(tmp_path: Path) -> None:
    """Rendered YAML loads back via load_simplify_order_target_spec."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml
    from src.mwcc_debug.simplify_order_scoring import load_simplify_order_target_spec

    baseline = tmp_path / "base.txt"
    baseline.write_text("pcdump", encoding="utf-8")
    yaml_text = render_simplify_order_target_yaml(
        function="gm_test",
        simplify_order_target=(34, 37, 32),
        class_id=0,
        baseline_dump=baseline,
        force_phys={34: 31, 37: 30, 32: 29},
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(yaml_text, encoding="utf-8")

    spec = load_simplify_order_target_spec(spec_path)
    assert spec.force_phys == {34: 31, 37: 30, 32: 29}


def test_render_target_yaml_omits_coalesce_preservation_when_default(tmp_path: Path) -> None:
    """When coalesce_preservation is True (default), the key is omitted
    from the rendered YAML — relies on the loader's default-true behavior."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml

    yaml_text = render_simplify_order_target_yaml(
        function="gm_test",
        simplify_order_target=(34, 37),
        class_id=0,
        baseline_dump=tmp_path / "base.txt",
        force_phys={34: 31},
        coalesce_preservation=True,
    )
    assert "coalesce_preservation" not in yaml_text


def test_render_target_yaml_emits_coalesce_preservation_when_false(tmp_path: Path) -> None:
    """When coalesce_preservation is False, the key IS emitted."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml

    yaml_text = render_simplify_order_target_yaml(
        function="gm_test",
        simplify_order_target=(34, 37),
        class_id=0,
        baseline_dump=tmp_path / "base.txt",
        force_phys={34: 31},
        coalesce_preservation=False,
    )
    assert "coalesce_preservation: false" in yaml_text


def test_render_target_yaml_roundtrip_coalesce_preservation(tmp_path: Path) -> None:
    """Rendered YAML with coalesce_preservation: false loads back correctly."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml
    from src.mwcc_debug.simplify_order_scoring import load_simplify_order_target_spec

    baseline = tmp_path / "base.txt"
    baseline.write_text("pcdump", encoding="utf-8")
    yaml_text = render_simplify_order_target_yaml(
        function="gm_test",
        simplify_order_target=(34,),
        class_id=0,
        baseline_dump=baseline,
        force_phys={34: 31},
        coalesce_preservation=False,
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(yaml_text, encoding="utf-8")

    spec = load_simplify_order_target_spec(spec_path)
    assert spec.coalesce_preservation is False


# ---------------------------------------------------------------------------
# render_simplify_order_target_yaml tests (simplify_order_target_late)
# ---------------------------------------------------------------------------


def test_render_target_yaml_with_late_target(tmp_path: Path) -> None:
    """When simplify_order_target_late is provided, render it instead
    of simplify_order_target."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml

    yaml_text = render_simplify_order_target_yaml(
        function="lbDvd_test",
        simplify_order_target=(),
        simplify_order_target_late=(46, 44),
        class_id=0,
        baseline_dump=tmp_path / "base.txt",
        force_phys={44: 10, 46: 12},
    )
    assert "simplify_order_target_late: [46, 44]" in yaml_text
    # The front target key should NOT appear when only late is set
    assert "simplify_order_target:" not in yaml_text


def test_render_target_yaml_late_roundtrip(tmp_path: Path) -> None:
    """Rendered YAML with simplify_order_target_late loads back correctly."""
    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml
    from src.mwcc_debug.simplify_order_scoring import load_simplify_order_target_spec

    baseline = tmp_path / "base.txt"
    baseline.write_text("pcdump", encoding="utf-8")
    yaml_text = render_simplify_order_target_yaml(
        function="lbDvd_test",
        simplify_order_target=(),
        simplify_order_target_late=(46, 44),
        class_id=0,
        baseline_dump=baseline,
        force_phys={44: 10, 46: 12},
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(yaml_text, encoding="utf-8")

    spec = load_simplify_order_target_spec(spec_path)
    assert spec.simplify_order_target_late == (46, 44)
    assert spec.simplify_order_target == ()


def test_render_target_yaml_both_or_neither_errors(tmp_path: Path) -> None:
    """Renderer requires exactly one of simplify_order_target or
    simplify_order_target_late."""
    import pytest

    from src.mwcc_debug.permuter_config import render_simplify_order_target_yaml

    # Both -> error
    with pytest.raises(ValueError, match="exactly one"):
        render_simplify_order_target_yaml(
            function="x",
            simplify_order_target=(1, 2),
            simplify_order_target_late=(3, 4),
            class_id=0,
            baseline_dump=tmp_path / "base.txt",
        )

    # Neither -> error
    with pytest.raises(ValueError, match="exactly one"):
        render_simplify_order_target_yaml(
            function="x",
            simplify_order_target=(),
            simplify_order_target_late=(),
            class_id=0,
            baseline_dump=tmp_path / "base.txt",
        )
