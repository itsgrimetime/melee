"""Tier 3 orchestrator: seed planner + multi-start search."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .mutators import (
    MutationUnsupported,
    mutate_insert_alias_before_use,
    mutate_type_change,
)
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


@dataclass
class MaterializedSeed:
    """A seed source written to disk + its plan."""
    plan: SeedPlan
    source_path: Path        # the mutated .c file
    seed_dir: Path           # nonmatchings/<fn>/tier3_seed_<idx>/
    compiles: bool           # set after the smoke compile


def materialize_seed(
    base_source: str,
    fn_name: str,
    plan: SeedPlan,
    seed_dir: Path,
) -> Optional[Path]:
    """Apply the plan to base_source, write result to seed_dir/base.c.

    Returns the path to the written .c, or None if the mutation
    raises MutationUnsupported.
    """
    try:
        if plan.mutator == "type-change":
            mutated = mutate_type_change(
                base_source, fn_name, plan.target_var,
                plan.args["new_type"],
            )
        elif plan.mutator == "insert-alias":
            mutated = mutate_insert_alias_before_use(
                base_source, fn_name, plan.target_var,
                at_stmt_index=plan.args["at_stmt_index"],
            )
        else:
            return None
    except MutationUnsupported:
        return None

    seed_dir.mkdir(parents=True, exist_ok=True)
    out = seed_dir / "base.c"
    out.write_text(mutated)
    return out


def smoke_compile(
    seed_source_path: Path,
    wibo: Path,
    debug_compiler: Path,
    cflags: str,
    cwd: Path,
) -> bool:
    """Quick compile attempt - returns True iff the .o is produced
    successfully. Discards the .o.

    Runs from `cwd` (typically the melee repo root) so the `-I` paths
    in cflags resolve correctly. The seed source itself is passed
    relative to cwd when possible, falling back to an absolute path
    when the seed lives outside cwd (e.g. in the decomp-permuter
    workspace).
    """
    out_o = Path("/tmp/tier3_smoke.o")
    if out_o.exists():
        out_o.unlink()

    try:
        src_arg = str(seed_source_path.relative_to(cwd))
    except ValueError:
        src_arg = str(seed_source_path)

    args = (
        [str(wibo), str(debug_compiler)]
        + shlex.split(cflags)
        + ["-c", src_arg, "-o", str(out_o)]
    )
    try:
        proc = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        return proc.returncode == 0 and out_o.exists()
    except subprocess.TimeoutExpired:
        return False
