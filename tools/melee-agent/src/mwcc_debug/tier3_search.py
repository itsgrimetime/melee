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
    bindings: list[Binding],
    budget: int = 5,
    include_low_confidence: bool = False,
) -> list[SeedPlan]:
    """Given the function's variable bindings, propose up to `budget`
    seed mutations in priority order.

    Priority:
      1. Locals with confidence='best-guess' or 'verified'
      2. Pointer locals -> alias-split before first use
      3. Integer locals -> type-change widening + shrinking variants
    Bindings with kind='param' or confidence in {ambiguous, unsupported,
    rejected, low-confidence} are skipped by default.

    `include_low_confidence`: also accept 'low-confidence' bindings.
    Useful when the function has red flags (nested decls, statics,
    extra-virtuals) and you've manually verified the mapping via
    `var-to-virtual --basis`. Off by default to avoid generating bad
    seeds for functions where the bridge's cursor model is unreliable.
    """
    accepted = {"best-guess", "verified"}
    if include_low_confidence:
        accepted = accepted | {"low-confidence"}

    plans: list[SeedPlan] = []

    for b in bindings:
        if b.kind != "local":
            continue
        if b.confidence not in accepted:
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


@dataclass
class CompileResult:
    """Outcome of a smoke-compile attempt, with enough detail for the
    agent to debug a failure manually."""
    ok: bool
    stderr: str         # full compiler stderr (empty if ok)
    stdout: str         # full compiler stdout (mostly empty)
    one_line_reason: str  # extracted first useful error line, or ""


def _extract_one_line_reason(stderr: str, stdout: str) -> str:
    """Pull the most-informative error line out of mwcc's output.

    MWCC errors look like:
        ### mwcceppc.exe Compiler:
        #    File: src/melee/mn/mnvibration.c
        # ----------------------------------
        # 1234:  bad code here
        # Error:   Illegal cast operation: ...
    We want the first "Error:" line (or the first line that contains
    "Error" or "syntax error"). Falls back to the first non-blank line
    if no error keyword matches.
    """
    lines = (stderr + "\n" + stdout).splitlines()
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # MWCC error pattern: "# Error: ..." or "Error: ..."
        low = s.lower()
        if "error:" in low or "syntax error" in low or "illegal" in low:
            # Strip leading '#' decoration that mwcc adds
            return s.lstrip("# ").strip()
    # Fallback: first non-blank non-decoration line
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#" + " " * 3) or s.startswith("---"):
            continue
        return s
    return "(no compiler diagnostic captured)"


def smoke_compile(
    seed_source_path: Path,
    wibo: Path,
    debug_compiler: Path,
    cflags: str,
    cwd: Path,
    extra_include_dirs: Optional[list[Path]] = None,
) -> CompileResult:
    """Quick compile attempt — returns a CompileResult with enough
    detail for the agent to debug a failure manually. Discards the .o.

    Runs from `cwd` (typically the melee repo root) so the `-I` paths
    in cflags resolve correctly. The seed source itself is passed
    relative to cwd when possible, falling back to an absolute path
    when the seed lives outside cwd (e.g. in the decomp-permuter
    workspace).

    `extra_include_dirs`: additional directories prepended to the MWCC
    include search path via `-i` flags. Use this when the seed source
    is staged outside the original TU directory so that quote-includes
    (e.g. `#include "mnvibration.h"`) can still resolve. Typically
    the parent directory of the original .c file.

    Returns:
        CompileResult with `ok`, captured `stderr`/`stdout`, and a
        `one_line_reason` summary extracted from the compiler output.
    """
    out_o = Path("/tmp/tier3_smoke.o")
    if out_o.exists():
        out_o.unlink()

    try:
        src_arg = str(seed_source_path.relative_to(cwd))
    except ValueError:
        src_arg = str(seed_source_path)

    extra_i_flags: list[str] = []
    for d in (extra_include_dirs or []):
        try:
            dir_arg = str(d.relative_to(cwd))
        except ValueError:
            dir_arg = str(d)
        extra_i_flags += ["-i", dir_arg]

    args = (
        [str(wibo), str(debug_compiler)]
        + shlex.split(cflags)
        + extra_i_flags
        + ["-c", src_arg, "-o", str(out_o)]
    )
    try:
        proc = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        ok = proc.returncode == 0 and out_o.exists()
        if ok:
            return CompileResult(ok=True, stderr="", stdout="", one_line_reason="")
        return CompileResult(
            ok=False,
            stderr=proc.stderr or "",
            stdout=proc.stdout or "",
            one_line_reason=_extract_one_line_reason(
                proc.stderr or "", proc.stdout or ""),
        )
    except subprocess.TimeoutExpired:
        return CompileResult(
            ok=False, stderr="", stdout="",
            one_line_reason="compile timed out (>30s)",
        )


def save_compile_failure(seed_dir: Path, result: CompileResult) -> Path:
    """Write the failed compile's stderr+stdout to a log inside seed_dir.
    Returns the path to the written log."""
    log_path = seed_dir / "compile_error.txt"
    seed_dir.mkdir(parents=True, exist_ok=True)
    body = []
    body.append(f"# Compile failed for {seed_dir / 'base.c'}\n")
    body.append(f"# One-line reason: {result.one_line_reason}\n\n")
    if result.stderr:
        body.append("=== stderr ===\n")
        body.append(result.stderr)
        if not result.stderr.endswith("\n"):
            body.append("\n")
        body.append("\n")
    if result.stdout:
        body.append("=== stdout ===\n")
        body.append(result.stdout)
        if not result.stdout.endswith("\n"):
            body.append("\n")
    log_path.write_text("".join(body))
    return log_path
