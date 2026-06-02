from __future__ import annotations
from itertools import combinations


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
