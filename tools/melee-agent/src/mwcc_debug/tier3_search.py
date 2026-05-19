"""Tier 3 orchestrator: seed planner + multi-start search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .symbol_bridge import Binding


_INTEGER_TYPES = {"u8", "u16", "u32", "s8", "s16", "s32", "int", "long"}
_POINTER_SUFFIXES = ("*",)

# Per-pattern seed expansions: source-type -> list of new types to try.
# v1 keeps this small; expanded as Tier 3 matures.
_TYPE_VARIANTS: dict[str, list[str]] = {
    "u8": ["u32", "s8"],
    "u16": ["u32", "s16"],
    "s8": ["u8", "s32"],
    "s16": ["s32", "u16"],
    "u32": ["s32", "u8"],
    "s32": ["u32", "s8"],
    "int": ["long", "short"],
}


@dataclass
class SeedPlan:
    """One planned seed to materialize + score."""
    mutator: str            # "type-change" | "insert-alias"
    target_var: str
    args: dict              # mutator-specific args
    description: str        # human-readable; goes into logs + reports


def plan_seeds(
    bindings: list[Binding], budget: int = 5,
) -> list[SeedPlan]:
    """Given the function's variable bindings, propose up to `budget`
    seed mutations in priority order.

    Priority:
      1. Locals with confidence='best-guess' or 'verified'
      2. Pointer locals -> alias-split before first use
      3. Integer locals -> type-change widening + shrinking variants
    Bindings with kind='param' or confidence in {ambiguous, unsupported,
    rejected} are skipped.
    """
    plans: list[SeedPlan] = []

    for b in bindings:
        if b.kind != "local":
            continue
        if b.confidence not in ("best-guess", "verified"):
            continue

        # Pointer alias-split
        if any(b.type_str.endswith(s) for s in _POINTER_SUFFIXES):
            plans.append(SeedPlan(
                mutator="insert-alias",
                target_var=b.var_name,
                args={"at_stmt_index": 0},
                description=(
                    f"insert-alias before first use of "
                    f"{b.var_name} ({b.type_str})"
                ),
            ))
            continue

        # Integer type-change variants
        base = b.type_str.strip()
        for variant in _TYPE_VARIANTS.get(base, []):
            plans.append(SeedPlan(
                mutator="type-change",
                target_var=b.var_name,
                args={"new_type": variant},
                description=(
                    f"type-change {b.var_name}: {base} -> {variant}"
                ),
            ))

    return plans[:budget]
