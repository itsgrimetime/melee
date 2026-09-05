from __future__ import annotations
from itertools import combinations


# ---------------------------------------------------------------------------
# Phys-match metric (the GATE signal — Codex round 4 "Fix A").
#
# This measures progress toward the desired PHYSICAL register assignment
# (TargetRoleSpec.desired_phys / proof_force_phys), NOT iter-ordering vs a
# baseline.  The baseline IS the wall (9ACC scores 0/2 by construction), so a
# candidate scores higher ONLY by actually moving a role to its desired phys —
# a no-op reproducing the baseline coloring can never inflate this signal.
#
# The iter-ordering ``order_distance``/``displacement`` below are kept ONLY as
# diagnostic telemetry; they are never the gate signal.
# ---------------------------------------------------------------------------


def phys_assignment_buckets(
    proof_force_phys: dict,
    matched: dict,
    decisions_by_new_ig: dict,
) -> dict:
    """Bucket each desired (original_ig → desired_phys) role into one of
    satisfied / blocked / abstained by comparing the candidate's actual
    ``assigned_reg`` against ``desired_phys``.

    Parameters
    ----------
    proof_force_phys:
        ``{original_ig: desired_phys}`` — the desired physical register per role.
    matched:
        ``{new_ig: original_ig}`` from ``ReanchorResult.matched``.
    decisions_by_new_ig:
        ``{new_ig: ColorgraphDecision}`` for the candidate's coloring.

    Returns
    -------
    dict with keys ``"satisfied"``, ``"blocked"``, ``"abstained"`` — each a
    list of per-role record dicts (``original_ig``/``new_ig``/``desired_phys``/
    ``assigned_phys`` [+ ``reason`` for abstained]).  A role is:
      * satisfied  — reanchored to a decision whose ``assigned_reg == desired_phys``
      * blocked    — reanchored to a decision whose ``assigned_reg != desired_phys``
      * abstained  — could not be reanchored / no decision / no assignment
    """
    original_to_new = {orig: new for new, orig in (matched or {}).items()}
    satisfied: list[dict] = []
    blocked: list[dict] = []
    abstained: list[dict] = []
    for raw_orig, raw_desired in sorted((proof_force_phys or {}).items()):
        orig = int(raw_orig)
        desired = int(raw_desired)
        new_ig = original_to_new.get(orig)
        if new_ig is None and orig in decisions_by_new_ig:
            new_ig = orig
        if new_ig is None:
            abstained.append({
                "original_ig": orig, "new_ig": None,
                "desired_phys": desired, "assigned_phys": None,
                "reason": "not_reanchored",
            })
            continue
        decision = decisions_by_new_ig.get(new_ig)
        if decision is None:
            abstained.append({
                "original_ig": orig, "new_ig": new_ig,
                "desired_phys": desired, "assigned_phys": None,
                "reason": "missing_decision",
            })
            continue
        assigned = getattr(decision, "assigned_reg", None)
        if assigned is None:
            abstained.append({
                "original_ig": orig, "new_ig": new_ig,
                "desired_phys": desired, "assigned_phys": None,
                "reason": "missing_assignment",
            })
        elif int(assigned) == desired:
            satisfied.append({
                "original_ig": orig, "new_ig": new_ig,
                "desired_phys": desired, "assigned_phys": int(assigned),
            })
        else:
            blocked.append({
                "original_ig": orig, "new_ig": new_ig,
                "desired_phys": desired, "assigned_phys": int(assigned),
            })
    return {"satisfied": satisfied, "blocked": blocked, "abstained": abstained}


def phys_match_fraction(buckets: dict, total: int) -> float:
    """Fraction of roles at their desired phys: ``|satisfied| / total``.

    ``total`` is the role count (``len(proof_force_phys)``); a 0/N baseline
    scores 0.0, an all-matched candidate scores 1.0.
    """
    return len(buckets["satisfied"]) / max(total, 1)


def phys_mismatch_count(buckets: dict) -> int:
    """Count of roles NOT at their desired phys (``blocked + abstained``).

    ``0`` means every role reached its desired phys — the phys-swap win.
    """
    return len(buckets["blocked"]) + len(buckets["abstained"])


def candidate_iter_by_original_ig(matched: dict, decisions_by_new_ig: dict) -> dict:
    """matched = {new_ig: original_ig}; returns {original_ig: iter_idx}, skipping new_igs
    that have no decision."""
    return {orig: decisions_by_new_ig[new].iter_idx
            for new, orig in matched.items() if new in decisions_by_new_ig}


def order_distance(cand_iter_by_ig: dict, objective_iter_by_ig: dict) -> int:
    """Kendall pairwise inversions between candidate and objective order over the shared igs.
    Binary {0,1} for two roles: 0 == the (register-coloring) order flip achieved."""
    igs = [i for i in objective_iter_by_ig if i in cand_iter_by_ig]
    inv = 0
    for a, b in combinations(igs, 2):
        if (objective_iter_by_ig[a] < objective_iter_by_ig[b]) != (cand_iter_by_ig[a] < cand_iter_by_ig[b]):
            inv += 1
    return inv


def displacement(cand_iter_by_ig: dict, objective_iter_by_ig: dict) -> float:
    """Smooth pre-flip signal: mean closeness of each role pair's SIGNED iter-gap to the
    objective's, normalized so partial movement registers even without a discrete flip.
    NOT guaranteed monotone toward the flip; 1.0 when all gaps match the objective."""
    igs = [i for i in objective_iter_by_ig if i in cand_iter_by_ig]
    if len(igs) < 2:
        return 0.0
    tot, n = 0.0, 0
    for a, b in combinations(igs, 2):
        og = objective_iter_by_ig[a] - objective_iter_by_ig[b]
        cg = cand_iter_by_ig[a] - cand_iter_by_ig[b]
        scale = max(abs(og), abs(cg), 1)
        tot += 1.0 - abs(og - cg) / (2 * scale)
        n += 1
    return tot / n
