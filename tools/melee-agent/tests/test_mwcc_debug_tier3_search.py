"""Tests for the Tier 3 orchestrator's seed generator + planner."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.symbol_bridge import Binding
from src.mwcc_debug.tier3_search import (
    CompileResult,
    SeedPlan,
    _extract_one_line_reason,
    plan_seeds,
)


def _local(name: str, type_str: str, virtual: int = 33) -> Binding:
    return Binding(
        var_name=name, virtual=virtual, decl_line=1,
        kind="local", type_str=type_str, confidence="best-guess",
    )


def test_plan_seeds_emits_type_widen_and_shrink_for_locals() -> None:
    """For an integer local, plan both widening and shrinking seeds
    (let the score sort)."""
    bindings = [_local("count", "u8")]
    plans = plan_seeds(bindings, budget=10)
    descriptions = [p.description for p in plans]
    assert any(
        "type-change" in d and "count" in d for d in descriptions
    )
    # u8 -> u32 widen AND u8 -> s8 shrink expected
    assert sum("u32" in d for d in descriptions) >= 1
    assert sum("s8" in d for d in descriptions) >= 1


def test_plan_seeds_emits_alias_split_for_pointer_locals() -> None:
    """For a pointer local, plan an alias-split seed."""
    bindings = [_local("data", "HSD_GObj*")]
    plans = plan_seeds(bindings, budget=5)
    assert any(p.mutator == "insert-alias" for p in plans)


def test_plan_seeds_respects_budget() -> None:
    """If candidates exceed budget, truncate by priority order."""
    bindings = [_local(f"v{i}", "u8") for i in range(10)]
    plans = plan_seeds(bindings, budget=3)
    assert len(plans) == 3


def test_plan_seeds_skips_unsupported_confidence() -> None:
    """Bindings with confidence='unsupported' or 'ambiguous' are skipped."""
    bindings = [
        _local("ok", "u8"),
        Binding(
            var_name="bad", virtual=-1, decl_line=1,
            kind="local", type_str="u8", confidence="ambiguous",
        ),
    ]
    plans = plan_seeds(bindings, budget=10)
    target_vars = {p.target_var for p in plans}
    assert "ok" in target_vars
    assert "bad" not in target_vars


def test_plan_seeds_skips_low_confidence_by_default() -> None:
    """low-confidence bindings are skipped unless explicitly opted in."""
    bindings = [
        Binding(
            var_name="weak", virtual=33, decl_line=1,
            kind="local", type_str="u8", confidence="low-confidence",
        ),
    ]
    plans = plan_seeds(bindings, budget=10)
    assert plans == []


def test_plan_seeds_includes_low_confidence_when_opted_in() -> None:
    """With include_low_confidence=True, low-confidence bindings ARE used."""
    bindings = [
        Binding(
            var_name="weak", virtual=33, decl_line=1,
            kind="local", type_str="u8", confidence="low-confidence",
        ),
    ]
    plans = plan_seeds(bindings, budget=10, include_low_confidence=True)
    assert plans  # at least one plan generated
    assert all(p.target_var == "weak" for p in plans)


def test_plan_seeds_skips_params() -> None:
    """v1 mutators don't operate on params - skip them in planning."""
    bindings = [
        Binding(
            var_name="gobj", virtual=32, decl_line=1, kind="param",
            type_str="HSD_GObj*", confidence="best-guess",
        ),
        _local("data", "HSD_GObj*"),
    ]
    plans = plan_seeds(bindings, budget=10)
    target_vars = {p.target_var for p in plans}
    assert "gobj" not in target_vars
    assert "data" in target_vars


def test_extract_one_line_reason_picks_mwcc_error_line() -> None:
    """The MWCC error block has '# Error: ...' as the most useful line."""
    stderr = textwrap.dedent("""\
        ### mwcceppc.exe Compiler:
        #    File: src/melee/mn/mnvibration.c
        # ----------------------------------
        # 1234:  bad code here
        # Error:   Illegal cast operation: cannot cast 'int' to 'HSD_JObj*'
        # The rest is noise.
    """)
    reason = _extract_one_line_reason(stderr, "")
    assert "Illegal cast" in reason
    # Leading '#' decoration is stripped.
    assert not reason.startswith("#")


def test_extract_one_line_reason_syntax_error() -> None:
    """'syntax error' should be caught when 'error:' isn't there."""
    stderr = "Something benign\nfile:1: syntax error before token foo\n"
    reason = _extract_one_line_reason(stderr, "")
    assert "syntax error" in reason


def test_extract_one_line_reason_fallback_on_no_keyword() -> None:
    """If no error keyword appears, fall back to first non-blank line."""
    stderr = "\n\nweird output not matching keywords\n"
    reason = _extract_one_line_reason(stderr, "")
    assert "weird output" in reason


def test_extract_one_line_reason_empty_returns_placeholder() -> None:
    """Empty input returns the explicit no-diagnostic placeholder."""
    reason = _extract_one_line_reason("", "")
    assert "no compiler diagnostic" in reason


def test_compile_result_dataclass_default_ok_state() -> None:
    """Sanity check: a fresh ok=True result has empty error fields."""
    r = CompileResult(ok=True, stderr="", stdout="", one_line_reason="")
    assert r.ok is True
    assert r.one_line_reason == ""
