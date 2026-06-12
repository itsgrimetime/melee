"""solve_coloring — the §2 solve loop orchestrator + exit-code contract (§7).

Exit codes (verbatim, spec §7):
  0 = >=1 ACTIONABLE perturbation (resolved source object) found — an
      actionable single candidate OR an actionable pair hit (§4.1: exit-4 only
      when neither exists);
  3 = abstain: G1 imperfect / force-phys collision / target truncated /
      NOT register-only / EMPTY force-phys target (matched fn — N4; nothing to
      reach is an abstain, never a budgeted no-candidate);
  4 = no actionable perturbation <= max-perturb within frontier/cap/filter
      (budgeted no-candidate, §4.1); reason="window-order" when ALL surviving
      hits are window-order-flagged (§1.5 (c)).

Collaborators (preconditions_fn / enumerate_fn / realize_fn) are injected:
unit tests stub them; the calibration gate (Task 11) wires them to FROZEN real
artifacts through the production paths; the CLI (Task 14) wires them live.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src.search.solver.worksheet import (
    FilterSummary, PairEscalation, Worksheet,
)


@dataclass
class Preconditions:
    register_only: bool
    reachable: bool
    g1_rate: float
    phys_target: dict
    g1_truncated: bool
    force_phys_collision: bool


@dataclass
class SolveResult:
    exit_code: int
    reason: str
    worksheet: Optional[Worksheet] = None


def _abstain(reason: str) -> SolveResult:
    return SolveResult(exit_code=3, reason=reason)


def solve_coloring(*, function: str, class_id: int,
                   preconditions_fn: Callable,
                   enumerate_fn: Callable,
                   realize_fn: Callable,
                   max_perturb: int = 2,
                   frontier: int = 32) -> SolveResult:
    pre = preconditions_fn(function=function, class_id=class_id)

    # §2 step 1 / §4 ABSTAIN conditions — all BEFORE any enumeration.
    if not pre.register_only:
        return _abstain("checkdiff not register-only (admit set: "
                        "operand-register-or-offset / backend-ceiling / "
                        "normalized-structural-match)")
    if not pre.phys_target:
        return _abstain("empty force-phys target (matched / no residual); "
                        "nothing to reach")
    if pre.force_phys_collision or not pre.reachable:
        return _abstain("force-phys collision: target coloring unreachable "
                        "(the escape is a structurally different virtual)")
    if pre.g1_truncated:
        return _abstain("target IG truncated/incomplete; dispense untrustworthy")
    if pre.g1_rate < 1.0:
        return _abstain(f"G1 {pre.g1_rate:.3f} < 100% on complete nodes; "
                        "what-ifs untrustworthy")

    # §2 steps 3-5: enumerate (+ escalate), then realize/rank/assemble.
    enum_out = enumerate_fn(function=function, class_id=class_id,
                            phys_target=pre.phys_target, frontier=frontier,
                            max_perturb=max_perturb)
    bundle = realize_fn(function=function, class_id=class_id,
                        enum_out=enum_out, phys_target=pre.phys_target)

    pe = bundle.pair_escalation
    worksheet = Worksheet(
        function=function, class_id=class_id, g1_rate=pre.g1_rate,
        force_phys_target={str(k): v for k, v in pre.phys_target.items()},
        reachable=pre.reachable,
        filter_summary=FilterSummary(**bundle.filter_summary),
        candidates=list(bundle.candidates),
        tooling_leads=list(bundle.tooling_leads),
        window_order=list(bundle.window_order),
        pair_escalation=PairEscalation(
            ran=pe["ran"], reason=pe["reason"],
            frontier_size=pe.get("frontier_size", 0),
            frontier=[h.get("perturbation") if isinstance(h, dict) else h
                      for h in pe.get("frontier", [])],
            pair_hits=list(pe.get("pair_hits", []))),
        enumeration_truncated=bundle.enumeration_truncated,
        evals_per_kind=dict(bundle.evals_per_kind),
    )

    actionable_pairs = [h for h in pe.get("pair_hits", [])
                        if isinstance(h, dict) and h.get("actionable")]
    if worksheet.candidates or actionable_pairs:
        return SolveResult(exit_code=0, reason="actionable candidate(s) found",
                           worksheet=worksheet)

    # §1.5 (c): ALL surviving hits window-flagged -> exit 4, reason window-order.
    if worksheet.window_order and not worksheet.candidates:
        return SolveResult(exit_code=4, reason="window-order", worksheet=worksheet)

    return SolveResult(
        exit_code=4,
        reason=(f"no actionable candidate within budget "
                f"K={max_perturb}/F={frontier}/200k + §1.5 filter"),
        worksheet=worksheet)
