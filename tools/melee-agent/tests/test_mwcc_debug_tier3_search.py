"""Tests for the Tier 3 orchestrator's seed generator + planner."""

from __future__ import annotations

import textwrap

from src.mwcc_debug.symbol_bridge import Binding
from src.mwcc_debug.tier3_search import (
    SeedPlan,
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
