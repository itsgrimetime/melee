"""Rank source-shape probes by target COLORGRAPH select-order behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .colorgraph_parser import (
    ColorgraphSection,
    find_function,
    parse_hook_events,
)
from .pressure_explorer import PressureDelta


@dataclass(frozen=True)
class SelectOrderPairObjective:
    first_virtual: int
    second_virtual: int
    baseline_first_iter: int | None
    baseline_second_iter: int | None
    candidate_first_iter: int | None
    candidate_second_iter: int | None
    baseline_assigned_first: int | None
    baseline_assigned_second: int | None
    candidate_assigned_first: int | None
    candidate_assigned_second: int | None
    baseline_satisfied: bool
    candidate_satisfied: bool
    improved: bool
    baseline_gap: int | None
    candidate_gap: int | None
    baseline_present_count: int
    candidate_present_count: int
    candidate_missing_virtuals: tuple[int, ...]
    actionable_movement: bool
    distance_to_flip: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_virtual": self.first_virtual,
            "second_virtual": self.second_virtual,
            "baseline_first_iter": self.baseline_first_iter,
            "baseline_second_iter": self.baseline_second_iter,
            "candidate_first_iter": self.candidate_first_iter,
            "candidate_second_iter": self.candidate_second_iter,
            "baseline_assigned_first": self.baseline_assigned_first,
            "baseline_assigned_second": self.baseline_assigned_second,
            "candidate_assigned_first": self.candidate_assigned_first,
            "candidate_assigned_second": self.candidate_assigned_second,
            "baseline_satisfied": self.baseline_satisfied,
            "candidate_satisfied": self.candidate_satisfied,
            "improved": self.improved,
            "baseline_gap": self.baseline_gap,
            "candidate_gap": self.candidate_gap,
            "baseline_present_count": self.baseline_present_count,
            "candidate_present_count": self.candidate_present_count,
            "candidate_missing_virtuals": list(self.candidate_missing_virtuals),
            "actionable_movement": self.actionable_movement,
            "distance_to_flip": self.distance_to_flip,
        }


@dataclass(frozen=True)
class SelectOrderObjective:
    target_orders: tuple[SelectOrderPairObjective, ...]
    target_order_satisfied: bool
    target_order_improved: bool
    satisfied_count: int
    improved_count: int
    actionable_movement_count: int
    missing_count: int
    target_spill_removed: tuple[int, ...]
    spill_removed: tuple[int, ...]
    spill_added: tuple[int, ...]
    frame_delta: int | None
    match_percent: float | None
    sort_key: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_orders": [pair.to_dict() for pair in self.target_orders],
            "target_order_satisfied": self.target_order_satisfied,
            "target_order_improved": self.target_order_improved,
            "satisfied_count": self.satisfied_count,
            "improved_count": self.improved_count,
            "actionable_movement_count": self.actionable_movement_count,
            "missing_count": self.missing_count,
            "target_spill_removed": list(self.target_spill_removed),
            "spill_removed": list(self.spill_removed),
            "spill_added": list(self.spill_added),
            "frame_delta": self.frame_delta,
            "match_percent": self.match_percent,
            "sort_key": list(self.sort_key),
        }


def score_select_order_candidate(
    baseline_pcdump: str,
    candidate_pcdump: str,
    *,
    function: str,
    target_orders: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    class_id: int = 0,
    delta: PressureDelta | None = None,
    match_percent: float | None = None,
) -> SelectOrderObjective:
    """Score one candidate by whether requested virtuals are selected in order."""
    normalized_targets = tuple(
        (int(first), int(second)) for first, second in target_orders
    )
    baseline_section = _select_colorgraph_section(
        baseline_pcdump,
        function=function,
        class_id=class_id,
    )
    candidate_section = _select_colorgraph_section(
        candidate_pcdump,
        function=function,
        class_id=class_id,
    )
    baseline_order = _section_order_map(baseline_section)
    candidate_order = _section_order_map(candidate_section)
    baseline_assigned = _section_assigned_map(baseline_section)
    candidate_assigned = _section_assigned_map(candidate_section)

    pair_scores = tuple(
        _score_order_pair(
            first,
            second,
            baseline_order=baseline_order,
            candidate_order=candidate_order,
            baseline_assigned=baseline_assigned,
            candidate_assigned=candidate_assigned,
        )
        for first, second in normalized_targets
    )
    satisfied_count = sum(1 for pair in pair_scores if pair.candidate_satisfied)
    improved_count = sum(1 for pair in pair_scores if pair.improved)
    actionable_movement_count = sum(
        1 for pair in pair_scores if pair.actionable_movement
    )
    missing_count = sum(
        1
        for pair in pair_scores
        if pair.candidate_first_iter is None or pair.candidate_second_iter is None
    )
    target_virtuals = {
        virtual for pair in normalized_targets for virtual in pair
    }
    spill_removed = delta.spill_removed if delta is not None else ()
    spill_added = delta.spill_added if delta is not None else ()
    target_spill_removed = tuple(
        sorted(virtual for virtual in spill_removed if virtual in target_virtuals)
    )
    objective = SelectOrderObjective(
        target_orders=pair_scores,
        target_order_satisfied=bool(pair_scores)
        and satisfied_count == len(pair_scores)
        and missing_count == 0,
        target_order_improved=improved_count > 0,
        satisfied_count=satisfied_count,
        improved_count=improved_count,
        actionable_movement_count=actionable_movement_count,
        missing_count=missing_count,
        target_spill_removed=target_spill_removed,
        spill_removed=spill_removed,
        spill_added=spill_added,
        frame_delta=delta.frame_delta if delta is not None else None,
        match_percent=match_percent,
        sort_key=(),
    )
    return replace(objective, sort_key=_objective_sort_key(objective))


def rank_select_order_candidates(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return variants sorted by select-order objective, not terminal match percent."""
    ranked = [dict(variant) for variant in variants]
    ranked.sort(key=_variant_sort_key, reverse=True)
    for idx, variant in enumerate(ranked, start=1):
        variant["rank"] = idx
    return ranked


def render_select_order_variant(variant: dict[str, Any]) -> str:
    """Render one ranked select-order candidate for terminal output."""
    rank = variant.get("rank", "?")
    label = variant.get("label", "?")
    operator = variant.get("operator", "?")
    status = variant.get("status", "?")
    lines = [f"{rank}. {label} [{operator}]"]
    if status != "ok":
        lines.append(f"   failed: {variant.get('error', 'unknown error')}")
        if variant.get("source_retained"):
            lines.append(f"   source: {variant['source_retained']}")
        return "\n".join(lines)

    objective = variant["objective"]
    chain = variant.get("chain") or []
    if chain:
        lines.append("   chain: " + " -> ".join(str(step) for step in chain))
    provenance = (variant.get("probe") or {}).get("provenance") or {}
    if provenance.get("kind") == "call-return-compare-chain":
        values = provenance.get("compare_values") or []
        value_text = "/".join(str(value) for value in values) or "?"
        lines.append(
            "   provenance: "
            f"{provenance.get('call_expression', '?')} -> "
            f"{provenance.get('compare_var', '?')} compares {value_text}"
        )
    lines.append(
        "   objective: "
        f"target_order_satisfied={_yesno(objective.get('target_order_satisfied'))} "
        f"target_order_improved={_yesno(objective.get('target_order_improved'))} "
        f"satisfied={objective.get('satisfied_count', 0)} "
        f"actionable={objective.get('actionable_movement_count', 0)} "
        f"missing={objective.get('missing_count', 0)}"
    )
    target_spill_removed = objective.get("target_spill_removed") or []
    lines.append(
        "   target_spill_removed: "
        f"{_fmt_virtuals(target_spill_removed)}"
    )
    for pair in objective.get("target_orders", []):
        before = _fmt_iter_pair(
            pair.get("baseline_first_iter"),
            pair.get("baseline_second_iter"),
        )
        after = _fmt_iter_pair(
            pair.get("candidate_first_iter"),
            pair.get("candidate_second_iter"),
        )
        lines.append(
            "   "
            f"r{pair['first_virtual']}<r{pair['second_virtual']}: "
            f"{before} -> {after}; "
            f"satisfied={_yesno(pair.get('candidate_satisfied'))} "
            f"actionable={_yesno(pair.get('actionable_movement'))} "
            f"distance_to_flip={_fmt_optional_int(pair.get('distance_to_flip'))} "
            f"missing={_fmt_virtuals(pair.get('candidate_missing_virtuals') or [])}"
        )
    match = objective.get("match_percent")
    if isinstance(match, (int, float)):
        lines.append(f"   final_match_percent: {match:.3f}")
    else:
        lines.append("   final_match_percent: n/a")
    if variant.get("source_retained"):
        lines.append(f"   source: {variant['source_retained']}")
    return "\n".join(lines)


def _score_order_pair(
    first: int,
    second: int,
    *,
    baseline_order: dict[int, int],
    candidate_order: dict[int, int],
    baseline_assigned: dict[int, int],
    candidate_assigned: dict[int, int],
) -> SelectOrderPairObjective:
    baseline_first = baseline_order.get(first)
    baseline_second = baseline_order.get(second)
    candidate_first = candidate_order.get(first)
    candidate_second = candidate_order.get(second)
    baseline_gap = _gap(baseline_first, baseline_second)
    candidate_gap = _gap(candidate_first, candidate_second)
    baseline_satisfied = baseline_gap is not None and baseline_gap > 0
    candidate_satisfied = candidate_gap is not None and candidate_gap > 0
    baseline_present_count = sum(
        1 for value in (baseline_first, baseline_second) if value is not None
    )
    candidate_present_count = sum(
        1 for value in (candidate_first, candidate_second) if value is not None
    )
    candidate_missing_virtuals = tuple(
        virtual
        for virtual, value in (
            (first, candidate_first),
            (second, candidate_second),
        )
        if value is None
    )
    gap_moved_closer = (
        baseline_gap is not None
        and candidate_gap is not None
        and candidate_gap > baseline_gap
    )
    presence_changed = (
        (baseline_first is None) != (candidate_first is None)
        or (baseline_second is None) != (candidate_second is None)
    )
    actionable_movement = (
        candidate_satisfied
        or gap_moved_closer
        or (presence_changed and candidate_present_count > 0)
    )
    return SelectOrderPairObjective(
        first_virtual=first,
        second_virtual=second,
        baseline_first_iter=baseline_first,
        baseline_second_iter=baseline_second,
        candidate_first_iter=candidate_first,
        candidate_second_iter=candidate_second,
        baseline_assigned_first=baseline_assigned.get(first),
        baseline_assigned_second=baseline_assigned.get(second),
        candidate_assigned_first=candidate_assigned.get(first),
        candidate_assigned_second=candidate_assigned.get(second),
        baseline_satisfied=baseline_satisfied,
        candidate_satisfied=candidate_satisfied,
        improved=not baseline_satisfied and candidate_satisfied,
        baseline_gap=baseline_gap,
        candidate_gap=candidate_gap,
        baseline_present_count=baseline_present_count,
        candidate_present_count=candidate_present_count,
        candidate_missing_virtuals=candidate_missing_virtuals,
        actionable_movement=actionable_movement,
        distance_to_flip=_distance_to_flip(candidate_gap, baseline_gap),
    )


def _select_colorgraph_section(
    pcdump_text: str,
    *,
    function: str,
    class_id: int,
) -> ColorgraphSection:
    events = find_function(parse_hook_events(pcdump_text), function)
    if events is None:
        raise ValueError(f"{function} not found in pcdump")
    for section in events.colorgraph_sections:
        if section.class_id == class_id:
            return section
    raise ValueError(f"{function} has no COLORGRAPH DECISIONS for class {class_id}")


def _section_order_map(section: ColorgraphSection) -> dict[int, int]:
    order: dict[int, int] = {}
    for decision in section.decisions:
        if decision.ig_idx >= 0 and decision.ig_idx not in order:
            order[decision.ig_idx] = decision.iter_idx
    return order


def _section_assigned_map(section: ColorgraphSection) -> dict[int, int]:
    assigned: dict[int, int] = {}
    for decision in section.decisions:
        if decision.ig_idx >= 0 and decision.ig_idx not in assigned:
            assigned[decision.ig_idx] = decision.assigned_reg
    return assigned


def _gap(first_iter: int | None, second_iter: int | None) -> int | None:
    if first_iter is None or second_iter is None:
        return None
    return second_iter - first_iter


def _distance_to_flip(
    candidate_gap: int | None,
    baseline_gap: int | None,
) -> int | None:
    if candidate_gap is not None:
        return max(0, 1 - candidate_gap)
    if baseline_gap is not None:
        return max(1, 1 - baseline_gap)
    return None


def _objective_sort_key(objective: SelectOrderObjective) -> tuple[float, ...]:
    frame_improvement = 0.0
    if objective.frame_delta is not None and objective.frame_delta < 0:
        frame_improvement = float(-objective.frame_delta)
    match_percent = objective.match_percent if objective.match_percent is not None else -1.0
    gap_score = sum(
        float(pair.candidate_gap) if pair.candidate_gap is not None else -1000.0
        for pair in objective.target_orders
    )
    distance_score = -sum(
        float(pair.distance_to_flip)
        if pair.distance_to_flip is not None else 1000.0
        for pair in objective.target_orders
    )
    return (
        float(objective.target_order_satisfied),
        float(objective.satisfied_count),
        float(objective.target_order_improved),
        float(objective.improved_count),
        float(objective.actionable_movement_count),
        distance_score,
        -float(objective.missing_count),
        gap_score,
        float(len(objective.target_spill_removed)),
        float(len(objective.spill_removed)),
        -float(len(objective.spill_added)),
        frame_improvement,
        float(match_percent),
    )


def _variant_sort_key(variant: dict[str, Any]) -> tuple[float, ...]:
    if variant.get("status") != "ok":
        return (-1.0,)
    objective = variant.get("objective") or {}
    sort_key = objective.get("sort_key")
    if isinstance(sort_key, list):
        return tuple(float(item) for item in sort_key)
    if isinstance(sort_key, tuple):
        return tuple(float(item) for item in sort_key)
    return (0.0,)


def _fmt_iter_pair(first_iter: object, second_iter: object) -> str:
    left = "?" if first_iter is None else str(first_iter)
    right = "?" if second_iter is None else str(second_iter)
    return f"iter {left}/{right}"


def _fmt_virtuals(values: list[int] | tuple[int, ...]) -> str:
    if not values:
        return "-"
    return ",".join(f"r{value}" for value in values)


def _fmt_optional_int(value: object) -> str:
    return "?" if value is None else str(value)


def _yesno(value: object) -> str:
    return "yes" if bool(value) else "no"
