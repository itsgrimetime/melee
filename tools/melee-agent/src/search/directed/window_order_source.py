"""Source probes derived from register window-order fallback leads."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.search import statement_move


_UNSAFE_LABEL_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_label_part(value: object) -> str:
    cleaned = _UNSAFE_LABEL_CHARS_RE.sub("-", str(value).strip())
    return cleaned.strip("-") or "unknown"


def _attr_value(source_attr: Any, key: str) -> Any:
    if isinstance(source_attr, Mapping):
        return source_attr.get(key)
    return getattr(source_attr, key, None)


def _source_attr_dict(source_attr: Any) -> dict[str, Any]:
    if isinstance(source_attr, Mapping):
        return dict(source_attr)
    return {
        key: getattr(source_attr, key, None)
        for key in (
            "kind",
            "name",
            "type",
            "source_file",
            "source_line",
            "source_col",
            "expression",
            "base_virtual",
            "base_var",
            "field_offset",
            "field_name",
            "confidence",
        )
        if hasattr(source_attr, key)
    }


def _source_attr_for_ig(
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    target_ig: int,
) -> Any | None:
    if source_attributions is None:
        return None
    if target_ig in source_attributions:
        return source_attributions[target_ig]  # type: ignore[index]
    key = str(target_ig)
    if key in source_attributions:
        return source_attributions[key]  # type: ignore[index]
    return None


def _lead_target_ig(lead: Mapping[str, Any]) -> int | None:
    try:
        return int(lead["target_ig"])
    except (KeyError, TypeError, ValueError):
        return None


def _lead_direction(lead: Mapping[str, Any]) -> str | None:
    order_move = lead.get("order_move")
    if (
        not isinstance(order_move, list | tuple)
        or len(order_move) < 2
        or order_move[0] not in {"before", "after"}
    ):
        return None
    return str(order_move[0])


def _candidate_destinations(
    *,
    direction: str,
    unit: statement_move.MoveUnit,
    legal: Iterable[int],
) -> list[int]:
    lo, hi = unit.index_range
    if direction == "before":
        return sorted((dest for dest in legal if dest < lo))
    if direction == "after":
        return sorted((dest for dest in legal if dest > hi + 1), reverse=True)
    return []


def generate_window_order_source_probes(
    source_text: str,
    *,
    function: str,
    fallback_leads: Iterable[Mapping[str, Any]],
    source_attributions: Mapping[int, Any] | Mapping[str, Any] | None = None,
    max_probes: int = 8,
) -> list[LifetimeLayoutProbe]:
    """Generate conservative source moves for solver window-order fallback leads.

    A lead is source-actionable only when its target IG has a unique local
    source attribution and exactly one movable statement unit writes that local.
    Ambiguous or missing source bindings intentionally produce no probe.
    """

    limit = max(0, int(max_probes))
    if limit == 0:
        return []

    groups = statement_move.sibling_groups(source_text, function)
    if groups is None:
        return []

    source_bytes = source_text.encode("utf-8")
    escaped = statement_move.escaped_locals(source_text, function)
    movable_by_local: dict[str, list[tuple[
        statement_move.SiblingGroup,
        list[statement_move.SiblingStmt],
        statement_move.MoveUnit,
    ]]] = {}
    for group in groups:
        sibs = group.siblings
        locals_ = set(group.locals_)
        for unit in statement_move.extract_movable_units(sibs, locals_):
            if not statement_move._unit_owns_its_lines(unit, source_bytes):
                continue
            movable_by_local.setdefault(unit.write_base, []).append(
                (group, sibs, unit)
            )

    probes: list[LifetimeLayoutProbe] = []
    seen_source: set[str] = set()
    for lead in fallback_leads:
        if len(probes) >= limit:
            break
        target_ig = _lead_target_ig(lead)
        if target_ig is None:
            continue
        direction = _lead_direction(lead)
        if direction is None:
            continue
        source_attr = _source_attr_for_ig(source_attributions, target_ig)
        if source_attr is None:
            continue
        if _attr_value(source_attr, "kind") not in {None, "local"}:
            continue
        local_name = _attr_value(source_attr, "name")
        if not isinstance(local_name, str) or not local_name:
            continue
        matches = movable_by_local.get(local_name, [])
        if len(matches) != 1:
            continue

        group, sibs, unit = matches[0]
        legal = statement_move.legal_destinations(
            sibs,
            unit,
            escaped=escaped,
            locals_=set(group.locals_),
        )
        destinations = _candidate_destinations(
            direction=direction,
            unit=unit,
            legal=legal,
        )
        if not destinations:
            continue

        for dest in destinations:
            candidate_text = statement_move.apply_move(
                source_text,
                sibs,
                unit,
                dest,
            )
            if candidate_text == source_text or candidate_text in seen_source:
                continue
            seen_source.add(candidate_text)
            label = (
                "window-order-"
                f"ig{target_ig}-"
                f"{direction}-"
                f"{_safe_label_part(local_name)}-"
                f"{len(probes)}"
            )
            lo, hi = unit.index_range
            line_range = [
                sibs[lo].line_range[0],
                sibs[hi].line_range[1],
            ]
            probes.append(
                LifetimeLayoutProbe(
                    label=label,
                    operator="window-order-source-steering",
                    description=(
                        f"Move source local {local_name} {direction} the "
                        "solver window-order fallback anchor."
                    ),
                    source_text=candidate_text,
                    provenance={
                        "kind": "window-order-fallback-source-move",
                        "lead": dict(lead),
                        "source_attribution": _source_attr_dict(source_attr),
                        "moved_local": local_name,
                        "scope_depth": group.scope_depth,
                        "block_start_line": group.block_start_line,
                        "destination": dest,
                        "line_range": line_range,
                    },
                )
            )
            if len(probes) >= limit:
                break

    return probes
