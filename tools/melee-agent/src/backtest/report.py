from __future__ import annotations

from collections import defaultdict

ESTIMAND_CAVEAT = (
    "This measures P(tooling leads to the fix | a small-lever match exists in history). "
    "It is a PROXY for P(tooling leads to the fix | function is currently blocked). "
    "A high score means tooling can rediscover the easy, already-won levers; it is NOT "
    "evidence that tooling owns X% of the matching surface (the stuck frontier is excluded)."
)

_VERDICTS = ("SOLVED-BY-TOOLING", "PARTIAL", "GAP")


def coverage_matrix(cases: list, results: list) -> dict:
    by_id = {c["case_id"]: c for c in cases}
    matrix: dict = defaultdict(lambda: defaultdict(lambda: {v: 0 for v in _VERDICTS} | {"total": 0}))
    for r in results:
        case = by_id.get(r["case_id"])
        if not case:
            continue
        cell = matrix[case["lever_class"]][case["provenance"]]
        cell[r["rollup"]] += 1
        cell["total"] += 1
    return {lc: dict(pv) for lc, pv in matrix.items()}


def render_report(matrix: dict) -> str:
    lines = [ESTIMAND_CAVEAT, ""]
    for provenance in ("held_out", "in_corpus"):
        lines.append(f"== {provenance} ==")
        lines.append(f"{'lever_class':32} {'solved':>7} {'partial':>8} {'gap':>5} {'total':>6}")
        for lc in sorted(matrix):
            cell = matrix[lc].get(provenance)
            if not cell:
                continue
            lines.append(f"{lc:32} {cell['SOLVED-BY-TOOLING']:>7} {cell['PARTIAL']:>8} "
                         f"{cell['GAP']:>5} {cell['total']:>6}")
        lines.append("")
    return "\n".join(lines)
