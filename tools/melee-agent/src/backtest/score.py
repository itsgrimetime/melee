from __future__ import annotations

import hashlib
from typing import Optional


def generative_verdict(*, baseline_ndl: int, baseline_pct: float,
                       best_ndl: Optional[int], best_pct: Optional[float]) -> str:
    if best_ndl == 0:
        return "byte-match-reproduced"
    if best_ndl is None:
        return "no-progress"
    if best_ndl < baseline_ndl or (best_pct is not None and best_pct > baseline_pct + 0.05):
        return "improved-toward"
    return "no-progress"


def rollup_verdict(advisory: Optional[str], generative: Optional[str],
                   agent: Optional[str]) -> str:
    if generative == "byte-match-reproduced" or agent == "matched":
        return "SOLVED-BY-TOOLING"
    if advisory == "names-lever" or generative == "improved-toward" or agent == "improved":
        return "PARTIAL"
    return "GAP"


def select_escalation(results, cases_by_id, *, control_n: int = 12, seed_token: str = "backtest"):
    must = [r["case_id"] for r in results if r["rollup"] in ("GAP", "PARTIAL")]
    solved_heldout = [
        r["case_id"] for r in results
        if r["rollup"] == "SOLVED-BY-TOOLING"
        and cases_by_id.get(r["case_id"], {}).get("provenance") == "held_out"
    ]
    solved_heldout.sort(key=lambda cid: hashlib.sha256((seed_token + cid).encode()).hexdigest())
    return must + solved_heldout[:control_n]
