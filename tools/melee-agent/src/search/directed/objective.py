"""DirectedObjective builder and pre-flight validation.

Pre-flight is the load-bearing gate that prevents "VOID" runs: a search must
ABORT LOUDLY if the target cannot be diagnosed (empty roles, or divergence case
NONE/ABSTAINED), so a silent non-result can never masquerade as "no progress."

build_directed_objective creates a fully-populated DirectedObjective from a
function name, unit, and a proof_force_phys dict.  The live end-to-end path
(which calls the real backend and live mwcc-debug analysis) is exercised at
Task 12; this module is kept structurally correct and importable from here.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional

from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events
from src.mwcc_debug.convergence import analyze_iteration_full
from src.mwcc_debug.role_descriptor import Compile, build_target_spec
from src.search.directed.contracts import DirectedObjective
from src.search.types import SourceVariant


# ---------------------------------------------------------------------------
# Module-level constant: force-phys map for grIceMt_801F9ACC register swap.
#
# Derived at Task 12 from live pcdump analysis of the current source
# (melee-agent debug dump local src/melee/gr/gricemt.c --function grIceMt_801F9ACC):
#
#   Block 1 of "BEFORE GLOBAL OPTIMIZATION" pass sets up params:
#     mr r32,r3   → ig_idx=32 = gobj     → currently r31
#     mr r33,r4   → ig_idx=33 = y(float  → currently r29  ← SWAP TARGET
#                                shadow)
#     mr r34,r5   → ig_idx=34 = ev       → currently r28  (stable, not swapped)
#   Block 2:
#     li r40,0    → ig_idx=40 = did=0    → currently r27  ← SWAP TARGET
#
#   Expected assembly (from checkdiff baseline diff):
#     addi r27,r4,0  → y-shadow should get r27
#     li   r29,0     → did should get r29
#
#   Desired coloring: ig_idx=33 → r27, ig_idx=40 → r29.
#   (The project notes' "ev→r27, did→r29" used older ig numbering; the
#   current source version maps y-shadow as ig39→r29 in the memory note
#   but after source changes the node indices are 33 and 40.)
# ---------------------------------------------------------------------------
GRICEMT_9ACC_FORCE_PHYS: dict = {33: 27, 40: 29}  # ig_idx→desired_phys


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PreflightError(Exception):
    """Raised when a DirectedObjective fails pre-flight validation.

    The message carries a short reason token so callers can route on it:
      "no_roles"      — role_target.roles is empty/falsy
      "case_<x>"      — divergence case is NONE or ABSTAINED
      "no_report"     — analyze() returned report=None
    """


class DirectedObjectiveBuildError(Exception):
    """Raised when a DirectedObjective cannot be built from live artifacts."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _case_str(c: Any) -> str:
    """Normalize a DivergenceCase (enum or raw string) to its value string."""
    return c.value if hasattr(c, "value") else str(c)


def _decisions_by_ig(pcdump_text: str, function: str, class_id: int) -> dict:
    """Return {ig_idx: ColorgraphDecision} for the target function and class.

    Takes the LAST ColorgraphSection with a matching class_id.  Falls back to
    the last section if none carries the requested class_id (tolerates pcdumps
    that pre-date the class_id field).
    """
    events = parse_hook_events(pcdump_text)
    fe = find_function(events, function)
    if fe is None or not fe.colorgraph_sections:
        return {}
    # Prefer the last section matching class_id; fall back to absolute last.
    matching = [s for s in fe.colorgraph_sections if s.class_id == class_id]
    section = matching[-1] if matching else fe.colorgraph_sections[-1]
    return {d.ig_idx: d for d in section.decisions}


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


def preflight_objective(
    obj: DirectedObjective,
    *,
    analyze: Callable = analyze_iteration_full,
) -> None:
    """Validate that *obj* is diagnosable before any search iteration runs.

    Raises PreflightError with a short reason token if validation fails.
    Returns None on success.

    Validation rules (all must pass):
      1. obj.role_target.roles is truthy (non-empty).
      2. The divergence case from analyze() is NOT NONE or ABSTAINED.
      3. The report from analyze() is not None.
    """
    # Rule 1: roles must be non-empty.
    if not obj.role_target.roles:
        raise PreflightError("no_roles")

    # Run analysis.
    state, report, _reanchor = analyze(
        obj.role_target, obj.baseline_compile, class_id=obj.class_id
    )

    # Rule 2: case must be actionable (not NONE or ABSTAINED).
    case_s = _case_str(state.fact.case)
    if case_s in {"none", "abstained"}:
        raise PreflightError(f"case_{case_s}")

    # Rule 3: report must not be None.
    if report is None:
        raise PreflightError("no_report")


# ---------------------------------------------------------------------------
# Objective builder (live path exercised at Task 12)
# ---------------------------------------------------------------------------


def build_directed_objective(
    *,
    melee_root: Any,
    search_target: Any,
    function: str,
    unit: str,
    proof_force_phys: dict,
    class_id: int = 0,
    backend: Any,
    baseline_source_text: str | None = None,
    parse_pcdump: Callable = _decisions_by_ig,
) -> DirectedObjective:
    """Build a DirectedObjective for *function* in *unit*.

    Steps:
      1. Compile the current TU source via *backend* to get a baseline pcdump.
      2. Build a Compile from the pcdump text.
      3. Build a TargetSpec (role_target) using *proof_force_phys*.
      4. Extract per-role iteration indices from the colorgraph decisions.
      5. Assemble and return the DirectedObjective.

    The live end-to-end path (real backend, real mwcc-debug analysis) is
    exercised at Task 12.  This function must be importable and structurally
    correct from Task 3 onward.
    """
    from pathlib import Path

    melee_root = Path(melee_root)
    tu_path = melee_root / "src" / f"{unit}.c"
    tu_source: str = (
        baseline_source_text
        if baseline_source_text is not None
        else tu_path.read_text(encoding="utf-8")
    )

    # Compile to get a baseline pcdump.
    artifact = backend.compile(SourceVariant(tu_source, None), want_pcdump=True)
    baseline_pcdump_path = artifact.pcdump_path
    if artifact.status != "ok" or baseline_pcdump_path is None:
        detail = getattr(artifact, "compiler_stderr", "") or ""
        detail = detail.strip()
        raise DirectedObjectiveBuildError(
            "baseline pcdump compile failed"
            + (f": {detail}" if detail else "")
        )
    pcdump_text: str = Path(baseline_pcdump_path).read_text(encoding="utf-8")

    # Build role structures.
    baseline_compile = Compile.from_text(pcdump_text, function, tu_source)
    role_target = build_target_spec(
        baseline_compile,
        proof_force_phys,
        class_id,
        "force_proof_proxy",
        {"src": "directed"},
    )

    # Map original_ig → colorgraph iter_idx from the baseline decisions.
    decisions = parse_pcdump(pcdump_text, function, class_id)
    objective_iter_by_original_ig: dict = {
        r.original_ig: decisions[r.original_ig].iter_idx
        for r in role_target.roles
        if r.original_ig in decisions
    }

    baseline_source_hash = hashlib.sha256(tu_source.encode()).hexdigest()[:32]

    return DirectedObjective(
        search_target=search_target,
        role_target=role_target,
        baseline_compile=baseline_compile,
        baseline_pcdump_path=baseline_pcdump_path,
        baseline_source_hash=baseline_source_hash,
        class_id=class_id,
        objective_iter_by_original_ig=objective_iter_by_original_ig,
        proof_force_phys=proof_force_phys,
    )
