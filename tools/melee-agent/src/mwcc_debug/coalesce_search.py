"""Rank source-shape probes by target virtual coalescing behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .pressure_explorer import PairDelta, PressureDelta


@dataclass(frozen=True)
class PairCoalesceObjective:
    virtual: int
    other_virtual: int
    target_coalesced: bool
    interference_removed: bool
    live_overlap_removed: bool
    before_interference: bool | None
    after_interference: bool | None
    before_live_overlap: bool | None
    after_live_overlap: bool | None
    before_same_assigned_reg: bool | None
    after_same_assigned_reg: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "virtual": self.virtual,
            "other_virtual": self.other_virtual,
            "target_coalesced": self.target_coalesced,
            "interference_removed": self.interference_removed,
            "live_overlap_removed": self.live_overlap_removed,
            "before_interference": self.before_interference,
            "after_interference": self.after_interference,
            "before_live_overlap": self.before_live_overlap,
            "after_live_overlap": self.after_live_overlap,
            "before_same_assigned_reg": self.before_same_assigned_reg,
            "after_same_assigned_reg": self.after_same_assigned_reg,
        }


@dataclass(frozen=True)
class CoalesceObjective:
    target_pairs: tuple[PairCoalesceObjective, ...]
    target_coalesced: bool
    interference_removed: bool
    live_overlap_removed: bool
    target_spill_removed: tuple[int, ...]
    spill_removed: tuple[int, ...]
    spill_added: tuple[int, ...]
    interference_removed_count: int
    interference_added_count: int
    coalesce_added_count: int
    coalesce_removed_count: int
    frame_delta: int | None
    match_percent: float | None
    sort_key: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_pairs": [pair.to_dict() for pair in self.target_pairs],
            "target_coalesced": self.target_coalesced,
            "interference_removed": self.interference_removed,
            "live_overlap_removed": self.live_overlap_removed,
            "target_spill_removed": list(self.target_spill_removed),
            "spill_removed": list(self.spill_removed),
            "spill_added": list(self.spill_added),
            "interference_removed_count": self.interference_removed_count,
            "interference_added_count": self.interference_added_count,
            "coalesce_added_count": self.coalesce_added_count,
            "coalesce_removed_count": self.coalesce_removed_count,
            "frame_delta": self.frame_delta,
            "match_percent": self.match_percent,
            "sort_key": list(self.sort_key),
        }


def score_coalesce_delta(
    delta: PressureDelta,
    *,
    target_pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...],
    match_percent: float | None = None,
) -> CoalesceObjective:
    """Score one pressure delta for a requested virtual-register relationship."""
    normalized_targets = tuple(_normalize_pair(pair) for pair in target_pairs)
    target_pair_set = set(normalized_targets)
    pair_deltas = {
        _normalize_pair((pair.before.virtual, pair.before.other_virtual)): pair
        for pair in delta.target_pairs
    }
    interference_removed = {_normalize_pair(pair) for pair in delta.interference_removed}
    coalesce_added = {_normalize_pair(pair) for pair in delta.coalesce_added}

    pair_scores = tuple(
        _score_pair(
            pair,
            pair_deltas.get(pair),
            pair in interference_removed,
            pair in coalesce_added,
        )
        for pair in normalized_targets
    )
    target_virtuals = {virtual for pair in target_pair_set for virtual in pair}
    target_spill_removed = tuple(
        sorted(virtual for virtual in delta.spill_removed if virtual in target_virtuals)
    )
    target_coalesced = any(pair.target_coalesced for pair in pair_scores)
    removed_interference_count = sum(
        1 for pair in pair_scores if pair.interference_removed
    )
    removed_live_count = sum(1 for pair in pair_scores if pair.live_overlap_removed)
    objective = CoalesceObjective(
        target_pairs=pair_scores,
        target_coalesced=target_coalesced,
        interference_removed=removed_interference_count > 0,
        live_overlap_removed=removed_live_count > 0,
        target_spill_removed=target_spill_removed,
        spill_removed=delta.spill_removed,
        spill_added=delta.spill_added,
        interference_removed_count=removed_interference_count,
        interference_added_count=len(delta.interference_added),
        coalesce_added_count=len(delta.coalesce_added),
        coalesce_removed_count=len(delta.coalesce_removed),
        frame_delta=delta.frame_delta,
        match_percent=match_percent,
        sort_key=(),
    )
    return replace(objective, sort_key=_objective_sort_key(objective))


def rank_coalesce_candidates(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return variants sorted by coalesce objective, not terminal match percent."""
    ranked = [dict(variant) for variant in variants]
    ranked.sort(key=_variant_sort_key, reverse=True)
    for idx, variant in enumerate(ranked, start=1):
        variant["rank"] = idx
    return ranked


def render_coalesce_variant(variant: dict[str, Any]) -> str:
    """Render one ranked variant for terminal output."""
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
    target_pairs = objective.get("target_pairs", [])
    lines.append(
        "   objective: "
        f"target_coalesced={_yesno(objective.get('target_coalesced'))} "
        f"interference_removed={_yesno(objective.get('interference_removed'))} "
        f"live_overlap_removed={_yesno(objective.get('live_overlap_removed'))}"
    )
    target_spill_removed = objective.get("target_spill_removed") or []
    lines.append(
        "   target_spill_removed: "
        f"{_fmt_virtuals(target_spill_removed)}"
    )
    for pair in target_pairs:
        lines.append(
            "   "
            f"r{pair['virtual']}/r{pair['other_virtual']}: "
            f"coalesced={_yesno(pair.get('target_coalesced'))}; "
            "interference "
            f"{_bool_transition(pair.get('before_interference'), pair.get('after_interference'))}; "
            "live "
            f"{_bool_transition(pair.get('before_live_overlap'), pair.get('after_live_overlap'))}"
        )
    match = objective.get("match_percent")
    if isinstance(match, (int, float)):
        lines.append(f"   final_match_percent: {match:.3f}")
    else:
        lines.append("   final_match_percent: n/a")
    if variant.get("source_retained"):
        lines.append(f"   source: {variant['source_retained']}")
    return "\n".join(lines)


def _score_pair(
    pair: tuple[int, int],
    pair_delta: PairDelta | None,
    interference_removed_by_edge: bool,
    coalesce_added_by_edge: bool,
) -> PairCoalesceObjective:
    if pair_delta is None:
        return PairCoalesceObjective(
            virtual=pair[0],
            other_virtual=pair[1],
            target_coalesced=coalesce_added_by_edge,
            interference_removed=interference_removed_by_edge,
            live_overlap_removed=False,
            before_interference=None,
            after_interference=None,
            before_live_overlap=None,
            after_live_overlap=None,
            before_same_assigned_reg=None,
            after_same_assigned_reg=None,
        )
    after_same = pair_delta.after.same_assigned_reg
    interference_removed = (
        pair_delta.before.colorgraph_interference
        and not pair_delta.after.colorgraph_interference
    ) or interference_removed_by_edge
    live_overlap_removed = (
        pair_delta.before.live_overlap and not pair_delta.after.live_overlap
    )
    return PairCoalesceObjective(
        virtual=pair[0],
        other_virtual=pair[1],
        target_coalesced=(after_same is True) or coalesce_added_by_edge,
        interference_removed=interference_removed,
        live_overlap_removed=live_overlap_removed,
        before_interference=pair_delta.before.colorgraph_interference,
        after_interference=pair_delta.after.colorgraph_interference,
        before_live_overlap=pair_delta.before.live_overlap,
        after_live_overlap=pair_delta.after.live_overlap,
        before_same_assigned_reg=pair_delta.before.same_assigned_reg,
        after_same_assigned_reg=after_same,
    )


def _objective_sort_key(objective: CoalesceObjective) -> tuple[float, ...]:
    frame_improvement = 0.0
    if objective.frame_delta is not None and objective.frame_delta < 0:
        frame_improvement = float(-objective.frame_delta)
    match_percent = objective.match_percent if objective.match_percent is not None else -1.0
    return (
        float(objective.target_coalesced),
        float(sum(1 for pair in objective.target_pairs if pair.target_coalesced)),
        float(objective.interference_removed),
        float(objective.interference_removed_count),
        float(objective.live_overlap_removed),
        float(sum(1 for pair in objective.target_pairs if pair.live_overlap_removed)),
        float(len(objective.target_spill_removed)),
        float(len(objective.spill_removed)),
        -float(len(objective.spill_added)),
        -float(objective.interference_added_count),
        -float(objective.coalesce_removed_count),
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


def _normalize_pair(pair: tuple[int, int]) -> tuple[int, int]:
    left, right = pair
    return (left, right) if left <= right else (right, left)


def _yesno(value: object) -> str:
    return "yes" if value is True else "no"


def _bool_transition(before: object, after: object) -> str:
    return f"{_state(before)}->{_state(after)}"


def _state(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "?"


def _fmt_virtuals(values: list[int] | tuple[int, ...]) -> str:
    return ",".join(f"r{value}" for value in values) if values else "-"
