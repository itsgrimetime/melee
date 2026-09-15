from __future__ import annotations

from typing import Any

from .types import ScoreResult, Verdict


def classify_score(score: ScoreResult, *, epsilon: float = 0.05) -> Verdict:
    if not score.compiled:
        return "deinline_failed"
    if (score.delta_struct or 0) > 0:
        return "lever"
    if (score.delta_fuzzy or 0.0) > epsilon:
        return "fuzzy_only"
    return "neutral"


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int_number(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def parse_checkdiff_metrics(payload: dict[str, Any]) -> tuple[float | None, int | None]:
    pct = _number(payload.get("fuzzy_match_percent"))
    if pct is None:
        pct = _number(payload.get("match_percent"))
    ndl = _int_number(payload.get("normalized_diff_lines"))
    classification = payload.get("classification")
    if ndl is None and isinstance(classification, dict):
        gate = classification.get("structural_truth_gate")
        if isinstance(gate, dict):
            ndl = _int_number(gate.get("normalized_diff_lines"))
    structural = payload.get("structural")
    if ndl is None and isinstance(structural, dict):
        ndl = _int_number(structural.get("normalized_diff_lines"))
        if ndl is None:
            ndl = _int_number(structural.get("line_delta"))
    guard = payload.get("structural_guard")
    if ndl is None and isinstance(guard, dict):
        ndl = _int_number(guard.get("normalized_diff_lines"))
    return pct, ndl


def diff_scores(
    baseline_payload: dict[str, Any],
    deinlined_payload: dict[str, Any],
) -> ScoreResult:
    baseline_pct, baseline_ndl = parse_checkdiff_metrics(baseline_payload)
    deinlined_pct, deinlined_ndl = parse_checkdiff_metrics(deinlined_payload)
    delta_fuzzy = None
    if baseline_pct is not None and deinlined_pct is not None:
        delta_fuzzy = baseline_pct - deinlined_pct
    delta_struct = None
    if baseline_ndl is not None and deinlined_ndl is not None:
        delta_struct = deinlined_ndl - baseline_ndl
    return ScoreResult(
        compiled=True,
        baseline_pct=baseline_pct,
        deinlined_pct=deinlined_pct,
        delta_fuzzy=delta_fuzzy,
        baseline_ndl=baseline_ndl,
        deinlined_ndl=deinlined_ndl,
        delta_struct=delta_struct,
    )
