"""Assemble exact retail colorgraph decision facts from raw probe events."""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

_GPR_ORDER = [0] + list(range(3, 13)) + list(range(31, 12, -1))
_FPR_ORDER = list(range(14)) + list(range(31, 13, -1))
_CLASS_ORDER = {
    "gpr": _GPR_ORDER,
    "fpr": _FPR_ORDER,
}


def assemble_color_decisions(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return complete ``color_decision`` events from raw colorgraph probes.

    The GDB hook samples several PCs inside retail ``colorgraph``.  This helper
    keeps that hook mechanical by validating the event sequence and materializing
    the consumer-facing decision rows used by ``backend-trace.v1``.
    """

    builders: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for raw in raw_events:
        kind = raw.get("event")
        decision_id = _required_str(raw, "id", kind)
        if kind == "colorgraph_select_start":
            if decision_id in builders:
                raise ValueError(f"duplicate colorgraph_select_start {decision_id}")
            builders[decision_id] = {"start": dict(raw)}
        elif kind == "colorgraph_candidates_ready":
            builder = _require_builder(builders, decision_id, kind)
            if "terminal" in builder:
                raise ValueError(
                    "colorgraph_candidates_ready after terminal colorgraph event "
                    f"{decision_id}"
                )
            if "candidates" in builder:
                raise ValueError(f"duplicate colorgraph_candidates_ready {decision_id}")
            builder["candidates"] = dict(raw)
        elif kind in {"colorgraph_assignment", "colorgraph_spill"}:
            builder = _require_builder(builders, decision_id, kind)
            if "candidates" not in builder:
                raise ValueError(f"{kind} before colorgraph_candidates_ready {decision_id}")
            if "terminal" in builder:
                raise ValueError(f"duplicate terminal colorgraph event {decision_id}")
            builder["terminal"] = dict(raw)
        else:
            raise ValueError(f"unknown colorgraph event {kind!r}")

    return [_build_decision(decision_id, builder) for decision_id, builder in builders.items()]


def _build_decision(decision_id: str, builder: dict[str, Any]) -> dict[str, Any]:
    start = builder["start"]
    candidates = builder.get("candidates")
    if candidates is None:
        raise ValueError(f"{decision_id} missing colorgraph_candidates_ready")
    terminal = builder.get("terminal")
    if terminal is None:
        raise ValueError(f"{decision_id} missing colorgraph_assignment or colorgraph_spill")

    class_name = _required_str(start, "class_name", "colorgraph_select_start")
    phys_order = _phys_order(class_name)
    volatile_candidates = _mask_to_ordered(
        _required_int(candidates, "candidate_mask", "colorgraph_candidates_ready"),
        phys_order,
    )
    assigned_phys: int | None
    if terminal["event"] == "colorgraph_spill":
        assigned_phys = None
        candidate_phys_ordered = volatile_candidates
        chosen_source = "spill"
        decision_rule = "spill_no_available_color"
        spill = {"spilled": True, "reason": terminal.get("reason", "no_available_color")}
        volatile_after = list(start.get("volatile_pool_before", []))
        nonvolatile_after = dict(start.get("nonvolatile_dispense_before", {}))
        tie_rule = "none_spill"
    else:
        assigned_phys = _required_int(terminal, "assigned_phys", "colorgraph_assignment")
        chosen_source = _required_str(terminal, "chosen_source", "colorgraph_assignment")
        if chosen_source == "nonvolatile_dispense":
            nonvolatile_remaining = list(
                _required_dict(
                    start,
                    "nonvolatile_dispense_before",
                    "colorgraph_select_start",
                ).get("remaining", [])
            )
            if assigned_phys in nonvolatile_remaining:
                candidate_phys_ordered = nonvolatile_remaining
            else:
                candidate_phys_ordered = [
                    assigned_phys,
                    *[phys for phys in nonvolatile_remaining if phys != assigned_phys],
                ]
        else:
            candidate_phys_ordered = volatile_candidates
        if assigned_phys not in candidate_phys_ordered:
            raise ValueError(
                f"{decision_id} assigned_phys {assigned_phys} not in candidate set"
            )
        decision_rule = _required_str(terminal, "decision_rule", "colorgraph_assignment")
        volatile_after = list(terminal.get("volatile_pool_after", []))
        nonvolatile_after = dict(terminal.get("nonvolatile_dispense_after", {}))
        tie_rule = _required_str(terminal, "tie_rule", "colorgraph_assignment")
        spill = None

    blocked_candidates = list(candidates.get("blocked_candidates", []))
    decision = {
        "event": "color_decision",
        "class_id": _required_int(start, "class_id", "colorgraph_select_start"),
        "class_name": class_name,
        "id": decision_id,
        "ig_id": _required_int(start, "ig_id", "colorgraph_select_start"),
        "iter": _required_int(start, "iter", "colorgraph_select_start"),
        "assigned_phys": assigned_phys,
        "node_state_before_select": _required_dict(
            start, "node_state_before_select", "colorgraph_select_start"
        ),
        "reserved_or_precolored_filtered": list(
            start.get("reserved_or_precolored_filtered", [])
        ),
        "available_phys_ordered": _mask_to_ordered(
            _required_int(start, "available_mask", "colorgraph_select_start"),
            phys_order,
        ),
        "blocked_candidates": blocked_candidates,
        "candidate_phys_ordered": candidate_phys_ordered,
        "chosen_source": chosen_source,
        "volatile_pool_before": list(start.get("volatile_pool_before", [])),
        "volatile_pool_after": volatile_after,
        "nonvolatile_dispense_before": dict(
            start.get("nonvolatile_dispense_before", {})
        ),
        "nonvolatile_dispense_after": nonvolatile_after,
        "tie_rule": tie_rule,
        "blocked_by": _blocked_by(blocked_candidates),
        "decision_rule": decision_rule,
        "confidence": "observed-internal",
        "provenance": "retail-colorgraph-internal",
        "source_stage": "colorgraph",
    }
    if spill is not None:
        decision["spill"] = spill
    return decision


def _mask_to_ordered(mask: int, order: list[int]) -> list[int]:
    if mask < 0:
        raise ValueError(f"negative register mask {mask}")
    return [phys for phys in order if mask & (1 << phys)]


def _blocked_by(blocked_candidates: list[Any]) -> list[dict[str, int]]:
    blocked_by: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for blocked in blocked_candidates:
        if not isinstance(blocked, dict):
            raise ValueError("blocked candidate must be object")
        holder = blocked.get("holder_ig_id")
        phys = blocked.get("holder_assigned_phys", blocked.get("phys"))
        if not isinstance(holder, int):
            raise ValueError("blocked candidate missing holder_ig_id")
        if not isinstance(phys, int):
            raise ValueError("blocked candidate missing physical register")
        key = (holder, phys)
        if key not in seen:
            seen.add(key)
            blocked_by.append({"ig_id": holder, "phys": phys})
    return blocked_by


def _phys_order(class_name: str) -> list[int]:
    try:
        return _CLASS_ORDER[class_name]
    except KeyError as exc:
        raise ValueError(f"unknown register class {class_name!r}") from exc


def _require_builder(
    builders: OrderedDict[str, dict[str, Any]], decision_id: str, kind: Any
) -> dict[str, Any]:
    try:
        return builders[decision_id]
    except KeyError as exc:
        raise ValueError(f"{kind} {decision_id} arrived before colorgraph_select_start") from exc


def _required_str(raw: dict[str, Any], key: str, kind: Any) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{kind} missing {key}")
    return value


def _required_int(raw: dict[str, Any], key: str, kind: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{kind} missing integer {key}")
    return value


def _required_dict(raw: dict[str, Any], key: str, kind: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{kind} missing object {key}")
    return dict(value)
