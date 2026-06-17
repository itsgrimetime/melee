"""Rank source-shape probes by target COLORGRAPH select-order behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .colorgraph_parser import (
    ColorgraphSection,
    ColorgraphDecision,
    find_function,
    parse_hook_events,
)
from .parser import Function, Pass, analyze_function, parse_pcdump
from .pressure_explorer import PressureDelta


@dataclass(frozen=True)
class SelectOrderVirtualFact:
    virtual: int
    iter_idx: int | None
    assigned_reg: int | None
    degree: int | None
    n_interferers: int | None
    live_range: tuple[int, int] | None
    interferers: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "virtual": self.virtual,
            "iter_idx": self.iter_idx,
            "assigned_reg": self.assigned_reg,
            "degree": self.degree,
            "n_interferers": self.n_interferers,
            "live_range": (
                None if self.live_range is None else list(self.live_range)
            ),
            "interferers": list(self.interferers),
        }


@dataclass(frozen=True)
class SelectOrderProbeIntent:
    kind: str
    virtual: int
    interferer: int | None
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "virtual": self.virtual,
            "interferer": self.interferer,
            "description": self.description,
        }


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
    baseline_first_fact: SelectOrderVirtualFact | None
    baseline_second_fact: SelectOrderVirtualFact | None
    candidate_first_fact: SelectOrderVirtualFact | None
    candidate_second_fact: SelectOrderVirtualFact | None
    candidate_first_only_interferers: tuple[int, ...]
    candidate_second_only_interferers: tuple[int, ...]
    candidate_shared_interferers: tuple[int, ...]
    desired_first_degree_reduced: bool
    undesired_second_degree_increased: bool
    first_extra_interference_removed: tuple[int, ...]
    second_extra_interference_added: tuple[int, ...]
    targeted_interference_movement: bool
    probe_intents: tuple[SelectOrderProbeIntent, ...]

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
            "baseline_first_fact": _fact_to_dict(self.baseline_first_fact),
            "baseline_second_fact": _fact_to_dict(self.baseline_second_fact),
            "candidate_first_fact": _fact_to_dict(self.candidate_first_fact),
            "candidate_second_fact": _fact_to_dict(self.candidate_second_fact),
            "candidate_first_only_interferers": list(
                self.candidate_first_only_interferers
            ),
            "candidate_second_only_interferers": list(
                self.candidate_second_only_interferers
            ),
            "candidate_shared_interferers": list(
                self.candidate_shared_interferers
            ),
            "desired_first_degree_reduced": self.desired_first_degree_reduced,
            "undesired_second_degree_increased": (
                self.undesired_second_degree_increased
            ),
            "first_extra_interference_removed": list(
                self.first_extra_interference_removed
            ),
            "second_extra_interference_added": list(
                self.second_extra_interference_added
            ),
            "targeted_interference_movement": (
                self.targeted_interference_movement
            ),
            "probe_intents": [intent.to_dict() for intent in self.probe_intents],
        }


@dataclass(frozen=True)
class SelectOrderObjective:
    target_orders: tuple[SelectOrderPairObjective, ...]
    target_order_satisfied: bool
    target_order_improved: bool
    force_phys_targets: tuple[tuple[int, int], ...]
    force_phys_satisfied: bool | None
    force_phys_satisfied_count: int
    force_phys_missing: tuple[int, ...]
    force_phys_mismatches: tuple[tuple[int, int, int], ...]
    satisfied_count: int
    improved_count: int
    actionable_movement_count: int
    missing_count: int
    target_spill_removed: tuple[int, ...]
    spill_removed: tuple[int, ...]
    spill_added: tuple[int, ...]
    frame_delta: int | None
    match_percent: float | None
    opcode_shape_preserved: bool | None
    targeted_interference_movement_count: int
    sort_key: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_orders": [pair.to_dict() for pair in self.target_orders],
            "target_order_satisfied": self.target_order_satisfied,
            "target_order_improved": self.target_order_improved,
            "force_phys_targets": {
                str(virtual): phys
                for virtual, phys in self.force_phys_targets
            },
            "force_phys_satisfied": self.force_phys_satisfied,
            "force_phys_satisfied_count": self.force_phys_satisfied_count,
            "force_phys_missing": list(self.force_phys_missing),
            "force_phys_mismatches": {
                str(virtual): {"expected": expected, "actual": actual}
                for virtual, expected, actual in self.force_phys_mismatches
            },
            "satisfied_count": self.satisfied_count,
            "improved_count": self.improved_count,
            "actionable_movement_count": self.actionable_movement_count,
            "missing_count": self.missing_count,
            "target_spill_removed": list(self.target_spill_removed),
            "spill_removed": list(self.spill_removed),
            "spill_added": list(self.spill_added),
            "frame_delta": self.frame_delta,
            "match_percent": self.match_percent,
            "opcode_shape_preserved": self.opcode_shape_preserved,
            "targeted_interference_movement_count": (
                self.targeted_interference_movement_count
            ),
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
    proof_force_phys: dict[int, int] | None = None,
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
    baseline_facts = _target_virtual_facts(
        baseline_pcdump,
        function=function,
        section=baseline_section,
        virtuals={virtual for pair in normalized_targets for virtual in pair},
    )
    candidate_facts = _target_virtual_facts(
        candidate_pcdump,
        function=function,
        section=candidate_section,
        virtuals={virtual for pair in normalized_targets for virtual in pair},
    )

    pair_scores = tuple(
        _score_order_pair(
            first,
            second,
            baseline_order=baseline_order,
            candidate_order=candidate_order,
            baseline_assigned=baseline_assigned,
            candidate_assigned=candidate_assigned,
            baseline_facts=baseline_facts,
            candidate_facts=candidate_facts,
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
    force_phys_targets = tuple(
        sorted((int(virtual), int(phys)) for virtual, phys in (proof_force_phys or {}).items())
    )
    force_phys_missing = tuple(
        virtual for virtual, _phys in force_phys_targets
        if virtual not in candidate_assigned
    )
    force_phys_mismatches = tuple(
        (virtual, phys, candidate_assigned[virtual])
        for virtual, phys in force_phys_targets
        if virtual in candidate_assigned and candidate_assigned[virtual] != phys
    )
    force_phys_satisfied_count = sum(
        1
        for virtual, phys in force_phys_targets
        if candidate_assigned.get(virtual) == phys
    )
    force_phys_satisfied = (
        None
        if not force_phys_targets
        else force_phys_satisfied_count == len(force_phys_targets)
        and not force_phys_missing
        and not force_phys_mismatches
    )
    spill_removed = delta.spill_removed if delta is not None else ()
    spill_added = delta.spill_added if delta is not None else ()
    target_spill_removed = tuple(
        sorted(virtual for virtual in spill_removed if virtual in target_virtuals)
    )
    targeted_interference_movement_count = sum(
        1 for pair in pair_scores if pair.targeted_interference_movement
    )
    objective = SelectOrderObjective(
        target_orders=pair_scores,
        target_order_satisfied=bool(pair_scores)
        and satisfied_count == len(pair_scores)
        and missing_count == 0,
        target_order_improved=improved_count > 0,
        force_phys_targets=force_phys_targets,
        force_phys_satisfied=force_phys_satisfied,
        force_phys_satisfied_count=force_phys_satisfied_count,
        force_phys_missing=force_phys_missing,
        force_phys_mismatches=force_phys_mismatches,
        satisfied_count=satisfied_count,
        improved_count=improved_count,
        actionable_movement_count=actionable_movement_count,
        missing_count=missing_count,
        target_spill_removed=target_spill_removed,
        spill_removed=spill_removed,
        spill_added=spill_added,
        frame_delta=delta.frame_delta if delta is not None else None,
        match_percent=match_percent,
        opcode_shape_preserved=_opcode_shape_preserved(
            baseline_pcdump,
            candidate_pcdump,
            function=function,
        ),
        targeted_interference_movement_count=targeted_interference_movement_count,
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
        f"targeted={objective.get('targeted_interference_movement_count', 0)} "
        f"missing={objective.get('missing_count', 0)} "
        f"opcode_shape_preserved={_fmt_optional_bool(objective.get('opcode_shape_preserved'))}"
    )
    force_phys_targets = objective.get("force_phys_targets") or {}
    if force_phys_targets:
        lines.append(
            "   force_phys: "
            f"satisfied={_fmt_optional_bool(objective.get('force_phys_satisfied'))} "
            f"matched={objective.get('force_phys_satisfied_count', 0)}/"
            f"{len(force_phys_targets)} "
            f"missing={_fmt_virtuals(objective.get('force_phys_missing') or [])} "
            f"mismatches={len(objective.get('force_phys_mismatches') or {})}"
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
        first_fact = pair.get("candidate_first_fact")
        second_fact = pair.get("candidate_second_fact")
        if isinstance(first_fact, dict):
            lines.append(f"      r{pair['first_virtual']} fact: {_fmt_fact(first_fact)}")
        if isinstance(second_fact, dict):
            lines.append(f"      r{pair['second_virtual']} fact: {_fmt_fact(second_fact)}")
        first_only = pair.get("candidate_first_only_interferers") or []
        second_only = pair.get("candidate_second_only_interferers") or []
        shared = pair.get("candidate_shared_interferers") or []
        if first_only or second_only or shared:
            lines.append(
                "      interferers: "
                f"first_only={_fmt_virtuals(first_only)} "
                f"second_only={_fmt_virtuals(second_only)} "
                f"shared={_fmt_virtuals(shared)}"
            )
        for intent in pair.get("probe_intents", [])[:4]:
            rendered = _fmt_probe_intent(intent)
            if rendered:
                lines.append(f"      probe-intent: {rendered}")
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
    baseline_facts: dict[int, SelectOrderVirtualFact],
    candidate_facts: dict[int, SelectOrderVirtualFact],
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
    baseline_first_fact = baseline_facts.get(first)
    baseline_second_fact = baseline_facts.get(second)
    candidate_first_fact = candidate_facts.get(first)
    candidate_second_fact = candidate_facts.get(second)
    candidate_first_only, candidate_second_only, candidate_shared = (
        _target_interferer_sets(
            first,
            second,
            candidate_first_fact,
            candidate_second_fact,
        )
    )
    baseline_first_only, baseline_second_only, _baseline_shared = (
        _target_interferer_sets(
            first,
            second,
            baseline_first_fact,
            baseline_second_fact,
        )
    )
    desired_first_degree_reduced = _degree_reduced(
        baseline_first_fact,
        candidate_first_fact,
    )
    undesired_second_degree_increased = _degree_increased(
        baseline_second_fact,
        candidate_second_fact,
    )
    first_extra_interference_removed = tuple(
        sorted(set(baseline_first_only) - set(candidate_first_only))
    )
    second_extra_interference_added = tuple(
        sorted(set(candidate_second_only) - set(baseline_second_only))
    )
    targeted_interference_movement = (
        desired_first_degree_reduced
        or undesired_second_degree_increased
        or bool(first_extra_interference_removed)
        or bool(second_extra_interference_added)
    )
    actionable_movement = (
        candidate_satisfied
        or gap_moved_closer
        or (presence_changed and candidate_present_count > 0)
        or targeted_interference_movement
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
        baseline_first_fact=baseline_first_fact,
        baseline_second_fact=baseline_second_fact,
        candidate_first_fact=candidate_first_fact,
        candidate_second_fact=candidate_second_fact,
        candidate_first_only_interferers=candidate_first_only,
        candidate_second_only_interferers=candidate_second_only,
        candidate_shared_interferers=candidate_shared,
        desired_first_degree_reduced=desired_first_degree_reduced,
        undesired_second_degree_increased=undesired_second_degree_increased,
        first_extra_interference_removed=first_extra_interference_removed,
        second_extra_interference_added=second_extra_interference_added,
        targeted_interference_movement=targeted_interference_movement,
        probe_intents=_probe_intents(
            first,
            second,
            candidate_satisfied=candidate_satisfied,
            candidate_first_fact=candidate_first_fact,
            candidate_second_fact=candidate_second_fact,
            candidate_first_only_interferers=candidate_first_only,
        ),
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


def _section_decision_map(section: ColorgraphSection) -> dict[int, ColorgraphDecision]:
    decisions: dict[int, ColorgraphDecision] = {}
    for decision in section.decisions:
        if decision.ig_idx >= 0 and decision.ig_idx not in decisions:
            decisions[decision.ig_idx] = decision
    return decisions


def _target_virtual_facts(
    pcdump_text: str,
    *,
    function: str,
    section: ColorgraphSection,
    virtuals: set[int],
) -> dict[int, SelectOrderVirtualFact]:
    decisions = _section_decision_map(section)
    live_ranges = _live_range_map(pcdump_text, function)
    facts: dict[int, SelectOrderVirtualFact] = {}
    for virtual in virtuals:
        decision = decisions.get(virtual)
        if decision is None:
            facts[virtual] = SelectOrderVirtualFact(
                virtual=virtual,
                iter_idx=None,
                assigned_reg=None,
                degree=None,
                n_interferers=None,
                live_range=live_ranges.get(virtual),
                interferers=(),
            )
            continue
        facts[virtual] = SelectOrderVirtualFact(
            virtual=virtual,
            iter_idx=decision.iter_idx,
            assigned_reg=decision.assigned_reg,
            degree=decision.degree,
            n_interferers=decision.n_interferers,
            live_range=live_ranges.get(virtual),
            interferers=tuple(
                sorted(
                    {
                        other
                        for other, _assigned in decision.interferers
                        if other >= 32
                    }
                )
            ),
        )
    return facts


def _live_range_map(pcdump_text: str, function: str) -> dict[int, tuple[int, int]]:
    parsed = parse_pcdump(pcdump_text, function=function)
    if not parsed:
        return {}
    return {
        info.virtual: (info.first_use, info.last_use)
        for info in analyze_function(parsed[0])
    }


def _target_interferer_sets(
    first: int,
    second: int,
    first_fact: SelectOrderVirtualFact | None,
    second_fact: SelectOrderVirtualFact | None,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    first_set = set() if first_fact is None else set(first_fact.interferers)
    second_set = set() if second_fact is None else set(second_fact.interferers)
    first_only = tuple(sorted((first_set - second_set) - {second}))
    second_only = tuple(sorted((second_set - first_set) - {first}))
    shared = tuple(sorted((first_set & second_set) - {first, second}))
    return first_only, second_only, shared


def _degree_reduced(
    baseline: SelectOrderVirtualFact | None,
    candidate: SelectOrderVirtualFact | None,
) -> bool:
    if baseline is None or candidate is None:
        return False
    if baseline.degree is None or candidate.degree is None:
        return False
    return candidate.degree < baseline.degree


def _degree_increased(
    baseline: SelectOrderVirtualFact | None,
    candidate: SelectOrderVirtualFact | None,
) -> bool:
    if baseline is None or candidate is None:
        return False
    if baseline.degree is None or candidate.degree is None:
        return False
    return candidate.degree > baseline.degree


def _probe_intents(
    first: int,
    second: int,
    *,
    candidate_satisfied: bool,
    candidate_first_fact: SelectOrderVirtualFact | None,
    candidate_second_fact: SelectOrderVirtualFact | None,
    candidate_first_only_interferers: tuple[int, ...],
) -> tuple[SelectOrderProbeIntent, ...]:
    if candidate_satisfied:
        return ()
    intents: list[SelectOrderProbeIntent] = []
    if candidate_first_fact is not None:
        intents.append(SelectOrderProbeIntent(
            kind="reduce-degree",
            virtual=first,
            interferer=None,
            description=(
                f"Reduce r{first}'s degree/lifetime so it can be selected "
                f"before r{second}."
            ),
        ))
    for interferer in candidate_first_only_interferers:
        intents.append(SelectOrderProbeIntent(
            kind="remove-interference",
            virtual=first,
            interferer=interferer,
            description=(
                f"Remove r{first}/r{interferer} interference to shrink the "
                "desired-first side."
            ),
        ))
    if candidate_second_fact is not None:
        intents.append(SelectOrderProbeIntent(
            kind="increase-degree",
            virtual=second,
            interferer=None,
            description=(
                f"Increase r{second}'s degree/lifetime so r{first} is not "
                "left behind in the selection order."
            ),
        ))
    for interferer in candidate_first_only_interferers:
        intents.append(SelectOrderProbeIntent(
            kind="add-interference",
            virtual=second,
            interferer=interferer,
            description=(
                f"Add harmless r{second}/r{interferer} interference to raise "
                "the undesired-first side."
            ),
        ))
    return tuple(intents)


def _opcode_shape_preserved(
    baseline_pcdump: str,
    candidate_pcdump: str,
    *,
    function: str,
) -> bool | None:
    baseline = _final_opcode_sequence(baseline_pcdump, function)
    candidate = _final_opcode_sequence(candidate_pcdump, function)
    if baseline is None or candidate is None:
        return None
    return baseline == candidate


def _final_opcode_sequence(pcdump_text: str, function: str) -> tuple[str, ...] | None:
    parsed = parse_pcdump(pcdump_text, function=function)
    if not parsed:
        return None
    selected = _select_final_pass(parsed[0])
    if selected is None:
        return None
    return tuple(
        instr.opcode
        for block in selected.blocks
        for instr in block.instructions
    )


def _select_final_pass(fn: Function) -> Pass | None:
    preferred = (
        "FINAL CODE AFTER INSTRUCTION SCHEDULING",
        "AFTER PEEPHOLE OPTIMIZATION",
        "AFTER MERGING EPILOGUE, PROLOGUE",
        "AFTER GENERATING EPILOGUE, PROLOGUE",
    )
    by_name = {pass_.name: pass_ for pass_ in fn.passes}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return fn.passes[-1] if fn.passes else None


def _fact_to_dict(fact: SelectOrderVirtualFact | None) -> dict[str, Any] | None:
    return None if fact is None else fact.to_dict()


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
    force_phys_requested = objective.force_phys_satisfied is not None
    return (
        float(objective.force_phys_satisfied is True) if force_phys_requested else 0.0,
        (
            float(objective.force_phys_satisfied_count)
            if force_phys_requested else 0.0
        ),
        (
            -float(len(objective.force_phys_missing))
            if force_phys_requested else 0.0
        ),
        (
            -float(len(objective.force_phys_mismatches))
            if force_phys_requested else 0.0
        ),
        float(objective.target_order_satisfied),
        float(objective.satisfied_count),
        float(objective.target_order_improved),
        float(objective.improved_count),
        float(objective.actionable_movement_count),
        float(objective.targeted_interference_movement_count),
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


def _fmt_optional_bool(value: object) -> str:
    if value is None:
        return "?"
    return _yesno(value)


def _fmt_fact(fact: dict[str, Any]) -> str:
    live = fact.get("live_range")
    if isinstance(live, list) and len(live) == 2:
        live_text = f"{live[0]}..{live[1]}"
    else:
        live_text = "?"
    degree = _fmt_optional_int(fact.get("degree"))
    n_interferers = _fmt_optional_int(fact.get("n_interferers"))
    return (
        f"live={live_text} "
        f"degree={degree} "
        f"nIntfr={n_interferers} "
        f"interferers={_fmt_virtuals(fact.get('interferers') or [])}"
    )


def _fmt_probe_intent(intent: dict[str, Any]) -> str:
    kind = intent.get("kind")
    virtual = intent.get("virtual")
    interferer = intent.get("interferer")
    if not isinstance(virtual, int):
        return ""
    if kind == "remove-interference" and isinstance(interferer, int):
        return f"remove r{virtual}/r{interferer} interference"
    if kind == "add-interference" and isinstance(interferer, int):
        return f"add r{virtual}/r{interferer} interference"
    if kind == "reduce-degree":
        return f"reduce r{virtual} degree/lifetime"
    if kind == "increase-degree":
        return f"increase r{virtual} degree/lifetime"
    description = intent.get("description")
    return str(description) if description else ""


def _yesno(value: object) -> str:
    return "yes" if bool(value) else "no"
