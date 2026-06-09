"""Phase-1 gate for the directed search layer.

Decides whether the directed mechanism is validated from a run's
``directed_telemetry`` (a list of :class:`DirectedMeta`).

Pass condition
--------------
The mechanism produced at least one *non-VOID, attributed, coverage-meeting,
displacement-improving* candidate whose final displacement exceeds the control
baseline.

Honest ``no_smooth_gradient`` outcome
--------------------------------------
Valid + attributed + covered treatment exists, but *no* candidate improved
displacement (delta <= 0 for all).  This is the expected result for a pure
register transposition that has no smooth gradient signal.  It is a *distinct*
verdict that routes to Phase 2, not a failure of the mechanism itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reason: str
    evidence: dict


def _case_str(c) -> str:
    return c.value if hasattr(c, "value") else str(c)


def evaluate_phase1_gate(
    preflight_ok: bool,
    telemetry: list,
    control_displacement: float,
    coverage_floor: float = 0.5,
) -> GateVerdict:
    """Evaluate the phase-1 gate.

    Parameters
    ----------
    preflight_ok:
        Whether the pre-flight checks passed (scratch compiles, objective set, etc.).
    telemetry:
        List of :class:`~src.search.directed.contracts.DirectedMeta` objects
        collected during the run.
    control_displacement:
        Displacement of the control (unmodified) baseline to beat.
    coverage_floor:
        Minimum ``reanchor_matched / reanchor_total`` ratio required for a
        candidate to be considered for passing.

    Returns
    -------
    GateVerdict
        ``passed=True`` with reason ``"attributable_progress"`` when a winner is
        found; ``passed=False`` with one of:

        * ``"not_preflight"`` — pre-flight failed
        * ``"void_no_treatment"`` — no valid, non-abstained candidates at all
        * ``"no_smooth_gradient"`` — valid + attributed + covered treatment exists
          but no displacement improvement (phase-2 territory)
        * ``"unattributed_or_regressing"`` — catch-all for missing mutator
          attribution or negative/zero delta without coverage issues
    """
    if not preflight_ok:
        return GateVerdict(False, "not_preflight", {})

    # Treatment = valid metas whose case is not "none" or "abstained".
    treatment = [
        m for m in telemetry
        if m.valid and _case_str(m.case) not in {"none", "abstained"}
    ]
    if not treatment:
        return GateVerdict(False, "void_no_treatment", {"n_telemetry": len(telemetry)})

    def _cov_ok(m) -> bool:
        return m.reanchor_matched / max(m.reanchor_total, 1) >= coverage_floor

    def _attributed(m) -> bool:
        # Attribution integrity (Codex round 4 P0): a candidate is attributed
        # ONLY if it has an applied_mutator AND that mutator came from an
        # ACTIONABLE (resolved-anchor) diagnosis.  The blind var_name=None
        # decl-pair fallback marks its candidates non_actionable, so a no-op
        # can never satisfy the attribution requirement.
        return bool(m.applied_mutator) and not getattr(m, "non_actionable", False)

    # A winner must be ATTRIBUTED, beat the REAL control baseline's phys-match
    # (displacement > control_displacement), show improvement vs its parent
    # (displacement_delta > 0), and meet coverage.
    winners = [
        m for m in treatment
        if _attributed(m)
        and m.displacement_delta > 0
        and _cov_ok(m)
        and m.displacement > control_displacement
    ]
    if winners:
        w = winners[0]
        return GateVerdict(
            True,
            "attributable_progress",
            {
                "applied_mutator": w.applied_mutator,
                "displacement": w.displacement,
                "displacement_delta": w.displacement_delta,
                "n_treatment": len(treatment),
            },
        )

    # No passing candidate.  Distinguish the honest "no gradient" outcome from
    # genuinely unattributed/regressing telemetry.
    #
    # "no_smooth_gradient": ATTRIBUTED (actionable) + covered treatment exists,
    # but no such candidate beat the control baseline's phys-match (every one
    # had displacement <= control AND/OR delta <= 0).  A pure register
    # transposition whose decl-order levers don't move any role to its desired
    # phys has no smooth signal; this routes to Phase 2.  This is the CORRECT,
    # valuable Phase-1 outcome, not a mechanism failure.
    attributed_covered = [m for m in treatment if _attributed(m) and _cov_ok(m)]
    if attributed_covered:
        return GateVerdict(
            False,
            "no_smooth_gradient",
            {
                "n_treatment": len(treatment),
                "n_attributed_covered": len(attributed_covered),
                "best_displacement": max(m.displacement for m in attributed_covered),
                "best_delta": max(m.displacement_delta for m in attributed_covered),
                "control_displacement": control_displacement,
            },
        )

    return GateVerdict(
        False,
        "unattributed_or_regressing",
        {
            "n_treatment": len(treatment),
            "n_non_actionable": sum(
                1 for m in treatment if getattr(m, "non_actionable", False)
            ),
        },
    )
