"""Targeted diagnostics for final-only stack-home mismatches."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .stack_slot_bridge import explain_stack_slot_localizer
from .virtual_attribution import explain_virtuals


def explore_stack_homes(
    pcdump_text: str,
    function: str,
    localizer: dict[str, Any],
    *,
    source_text: str | None = None,
    source_file: str | None = None,
    neighbor_window: int = 16,
    max_suggestions: int = 5,
) -> dict[str, Any]:
    """Build source-shape guidance for stack-home-only spill mismatches."""
    bridge = explain_stack_slot_localizer(
        pcdump_text,
        function,
        localizer,
        source_text=source_text,
        source_file=source_file,
    )
    bridge_candidates = list(bridge.get("candidates") or [])
    candidates = [
        candidate
        for candidate in bridge_candidates
        if _is_stack_home_candidate(candidate)
    ]
    lifetimes = _explain_lifetimes(
        pcdump_text,
        function,
        candidates,
        source_text=source_text,
        source_file=source_file,
    )

    targets = [
        _target_report(
            candidate,
            all_candidates=bridge_candidates,
            lifetimes=lifetimes,
            neighbor_window=neighbor_window,
            max_suggestions=max_suggestions,
        )
        for candidate in candidates
    ]
    targets.sort(key=_target_sort_key, reverse=True)
    for rank, target in enumerate(targets, start=1):
        target["rank"] = rank

    status = "ok" if targets else bridge.get("status", "no-candidates")
    return {
        "status": status,
        "function": function,
        "target_count": len(targets),
        "targets": targets,
        "ranking": {
            "primary_objective": "target-stack-home-offset",
            "target_movement_measured": False,
            "overall_match_percent_used": False,
            "note": (
                "Suggestions are ranked by target offset evidence before "
                "overall match percent because no variants were compiled."
            ),
        },
        "bridge": {
            "status": bridge.get("status"),
            "candidate_count": bridge.get("candidate_count", 0),
        },
    }


def render_stack_home_report_text(report: dict[str, Any]) -> str:
    lines = [
        f"stack-home explorer - {report.get('function')}",
        f"status: {report.get('status')}",
    ]
    targets = report.get("targets") or []
    if not targets:
        lines.append("no final-only stack-home targets found")
        return "\n".join(lines)
    for target in targets:
        current = _format_offset(target.get("current_offset"))
        expected = _format_offset(target.get("expected_offset"))
        lines.append("")
        lines.append(
            f"target #{target.get('rank')}: {target.get('opcode')} "
            f"{target.get('virtual_token')} -> {target.get('assigned_reg')} "
            f"{target.get('register_class_name')} "
            f"{current} -> {expected}"
        )
        source = target.get("source_expression") or {}
        expression = source.get("expression")
        if expression:
            lines.append(f"  source: {expression}")
        lifetime = target.get("lifetime") or {}
        first = lifetime.get("first_occurrence") or {}
        last = lifetime.get("last_occurrence") or {}
        if first:
            lines.append(
                "  first: "
                f"B{first.get('block_idx')}:{first.get('instr_idx')} "
                f"{first.get('opcode')} {first.get('operands')}"
            )
        if last and last != first:
            lines.append(
                "  last:  "
                f"B{last.get('block_idx')}:{last.get('instr_idx')} "
                f"{last.get('opcode')} {last.get('operands')}"
            )
        aliases = target.get("aliases") or {}
        natural = aliases.get("natural") or []
        if natural:
            rendered = ", ".join(
                f"f{item.get('alias')}->f{item.get('root')}"
                for item in natural
            )
            lines.append(f"  natural aliases: {rendered}")
        neighbors = target.get("neighboring_stack_homes") or []
        if neighbors:
            rendered = ", ".join(
                f"{_format_offset(item.get('offset'))}:{item.get('role')}"
                for item in neighbors
            )
            lines.append(f"  neighboring homes: {rendered}")
        suggestions = target.get("suggestions") or []
        if suggestions:
            lines.append("  suggestions:")
            for suggestion in suggestions:
                lines.append(
                    f"    {suggestion.get('rank')}. {suggestion.get('kind')}: "
                    f"{suggestion.get('description')}"
                )
                sketch = suggestion.get("edit_sketch")
                if sketch:
                    lines.append(f"       sketch: {sketch}")
    return "\n".join(lines)


def _is_stack_home_candidate(candidate: dict[str, Any]) -> bool:
    if candidate.get("site_kind") == "final-only-stack-home":
        return True
    opcode = str(candidate.get("opcode") or "")
    return (
        opcode in {"lfs", "lfd", "stfs", "stfd"}
        and candidate.get("current_offset") is not None
        and candidate.get("expected_offset") is not None
    )


def _explain_lifetimes(
    pcdump_text: str,
    function: str,
    candidates: list[dict[str, Any]],
    *,
    source_text: str | None,
    source_file: str | None,
) -> dict[tuple[int, int], dict[str, Any]]:
    by_class: dict[int, list[int]] = {}
    for candidate in candidates:
        class_id = _int_or_none(candidate.get("register_class"))
        virtual = _int_or_none(candidate.get("virtual"))
        if class_id is None or virtual is None:
            continue
        by_class.setdefault(class_id, []).append(virtual)

    out: dict[tuple[int, int], dict[str, Any]] = {}
    for class_id, virtuals in by_class.items():
        reg_class = "fpr" if class_id == 1 else "gpr"
        try:
            report = explain_virtuals(
                pcdump_text,
                function,
                virtuals=sorted(set(virtuals)),
                source_text=source_text,
                source_file=source_file,
                reg_class=reg_class,
            )
        except Exception as exc:
            for virtual in virtuals:
                out[(class_id, virtual)] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            continue
        for entry in report.virtuals:
            out[(class_id, entry.virtual)] = asdict(entry)
    return out


def _target_report(
    candidate: dict[str, Any],
    *,
    all_candidates: list[dict[str, Any]],
    lifetimes: dict[tuple[int, int], dict[str, Any]],
    neighbor_window: int,
    max_suggestions: int,
) -> dict[str, Any]:
    class_id = _int_or_none(candidate.get("register_class"))
    virtual = _int_or_none(candidate.get("virtual"))
    lifetime = (
        lifetimes.get((class_id, virtual), {})
        if class_id is not None and virtual is not None
        else {}
    )
    target = {
        "opcode": candidate.get("opcode"),
        "current_offset": candidate.get("current_offset"),
        "expected_offset": candidate.get("expected_offset"),
        "delta": candidate.get("delta"),
        "register_class": class_id,
        "register_class_name": _class_name(class_id),
        "virtual": virtual,
        "virtual_token": candidate.get("virtual_token"),
        "spill_root": candidate.get("spill_root"),
        "assigned_reg": candidate.get("assigned_reg"),
        "site_kind": candidate.get("site_kind"),
        "mapping_status": candidate.get("mapping_status"),
        "simplify": candidate.get("simplify") or {},
        "aliases": {
            "natural": candidate.get("natural_coalesce_aliases") or [],
            "coalesced": candidate.get("coalesced_aliases") or [],
        },
        "source_expression": _source_expression(candidate, lifetime),
        "lifetime": _lifetime_summary(lifetime),
        "neighboring_stack_homes": _neighboring_stack_homes(
            candidate,
            all_candidates,
            neighbor_window=neighbor_window,
        ),
        "evidence": list(candidate.get("evidence") or []),
    }
    target["suggestions"] = _suggestions_for_target(
        target,
        lifetime,
        max_suggestions=max_suggestions,
    )
    return target


def _target_sort_key(target: dict[str, Any]) -> tuple[int, int, int]:
    class_score = 1 if target.get("register_class") == 1 else 0
    final_score = 1 if target.get("site_kind") == "final-only-stack-home" else 0
    delta = abs(_int_or_none(target.get("delta")) or 0)
    return (class_score, final_score, delta)


def _source_expression(
    candidate: dict[str, Any],
    lifetime: dict[str, Any],
) -> dict[str, Any] | None:
    source = candidate.get("nearest_source_expression")
    if source:
        return source
    source = lifetime.get("source")
    if not isinstance(source, dict):
        return None
    expression = source.get("expression") or source.get("name")
    if not expression:
        return None
    return {
        "expression": expression,
        "confidence": source.get("confidence"),
        "source_file": source.get("source_file"),
        "source_line": source.get("source_line"),
        "source_col": source.get("source_col"),
    }


def _lifetime_summary(lifetime: dict[str, Any]) -> dict[str, Any]:
    if not lifetime:
        return {}
    source = lifetime.get("source")
    return {
        "status": lifetime.get("status"),
        "live_range": lifetime.get("live_range"),
        "live_blocks": lifetime.get("live_blocks") or [],
        "use_count": lifetime.get("use_count"),
        "first_occurrence": lifetime.get("first_occurrence"),
        "last_occurrence": lifetime.get("last_occurrence"),
        "source_kind": source.get("kind") if isinstance(source, dict) else None,
    }


def _neighboring_stack_homes(
    candidate: dict[str, Any],
    all_candidates: list[dict[str, Any]],
    *,
    neighbor_window: int,
) -> list[dict[str, Any]]:
    current = _int_or_none(candidate.get("current_offset"))
    expected = _int_or_none(candidate.get("expected_offset"))
    class_id = _int_or_none(candidate.get("register_class"))
    anchors = [value for value in (current, expected) if value is not None]
    seen: set[tuple[int, str, str | None]] = set()
    out: list[dict[str, Any]] = []

    def add(offset: int, role: str, item: dict[str, Any] | None = None) -> None:
        key = (offset, role, None if item is None else item.get("virtual_token"))
        if key in seen:
            return
        seen.add(key)
        out.append({
            "offset": offset,
            "role": role,
            "virtual_token": None if item is None else item.get("virtual_token"),
            "opcode": None if item is None else item.get("opcode"),
            "assigned_reg": None if item is None else item.get("assigned_reg"),
            "site_kind": None if item is None else item.get("site_kind"),
        })

    for item in all_candidates:
        if _int_or_none(item.get("register_class")) != class_id:
            continue
        offset = _int_or_none(item.get("current_offset"))
        if offset is None or not _near_any(offset, anchors, neighbor_window):
            continue
        role = "current-target" if offset == current else "neighbor-current"
        add(offset, role, item)

    for item in candidate.get("stack_home_order") or []:
        offset = _int_or_none(item.get("offset"))
        if offset is None or not _near_any(offset, anchors, neighbor_window):
            continue
        role = "precolor-home"
        add(offset, role, item)

    if expected is not None:
        add(expected, "expected-target", None)
    if current is not None and current != expected:
        add(current, "current-offset", None)

    out.sort(key=lambda item: (item["offset"], item["role"]))
    return out


def _suggestions_for_target(
    target: dict[str, Any],
    lifetime: dict[str, Any],
    *,
    max_suggestions: int,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    first = lifetime.get("first_occurrence") or {}
    first_opcode = str(first.get("opcode") or "").lower()
    source = target.get("source_expression") or {}
    expression = source.get("expression") or (
        f"{first_opcode} {first.get('operands')}"
        if first_opcode
        else "target expression"
    )
    objective = _target_offset_objective(target)

    if first_opcode == "fmr":
        suggestions.append(_suggestion(
            "remove-or-inline-copy-temp",
            (
                "Inline the float copy into its single downstream use, or "
                "name the source-side value instead of the copy."
            ),
            (
                "replace the separate copied float temp with a direct use of "
                f"the C expression that produced `{expression}`"
            ),
            objective,
            target,
            boost=30,
        ))

    if first_opcode in {
        "fadd",
        "fadds",
        "fsub",
        "fsubs",
        "fmul",
        "fmuls",
        "fdiv",
        "fdivs",
    }:
        suggestions.append(_suggestion(
            "split-binary-float-expression",
            (
                "Split the binary float expression into one adjacent named "
                "operand temp and the final expression."
            ),
            (
                "float operand_tmp = <one C operand>; "
                "float target_tmp = operand_tmp <op> <other operand>; "
                f"/* `{expression}` */"
            ),
            objective,
            target,
            boost=28,
        ))

    if target.get("register_class") == 1:
        suggestions.append(_suggestion(
            "introduce-named-float-temp",
            (
                "Name the target FPR expression immediately before its use "
                "to perturb reusable stack-home pressure locally."
            ),
            (
                "float target_tmp = <C expression for "
                f"`{expression}`>; use target_tmp at the original use"
            ),
            objective,
            target,
            boost=24,
        ))

    aliases = (target.get("aliases") or {}).get("natural") or []
    if aliases:
        suggestions.append(_suggestion(
            "narrow-alias-lifetime",
            (
                "Shorten the source lifetime for the coalesced alias cluster "
                "so the stack home can be assigned after nearby FPR temps."
            ),
            "move the aliased temp declaration into the smallest enclosing block",
            objective,
            target,
            boost=18,
        ))

    simplify = target.get("simplify") or {}
    if simplify.get("spilled"):
        suggestions.append(_suggestion(
            "lifetime-shortening-scope-block",
            (
                "Introduce a tiny block around the target computation to end "
                "the spilled FPR temp before unrelated float work."
            ),
            "{ float tmp = <target expression>; <existing use>; }",
            objective,
            target,
            boost=14,
        ))

    suggestions.sort(key=lambda item: item["_score"], reverse=True)
    out = []
    for rank, item in enumerate(suggestions[:max_suggestions], start=1):
        item = dict(item)
        item.pop("_score", None)
        item["rank"] = rank
        out.append(item)
    return out


def _suggestion(
    kind: str,
    description: str,
    edit_sketch: str,
    objective: dict[str, Any],
    target: dict[str, Any],
    *,
    boost: int,
) -> dict[str, Any]:
    score = boost
    if target.get("site_kind") == "final-only-stack-home":
        score += 20
    if target.get("register_class") == 1:
        score += 20
    if target.get("delta") is not None:
        score += abs(_int_or_none(target.get("delta")) or 0)
    if (target.get("aliases") or {}).get("natural"):
        score += 5
    if (target.get("simplify") or {}).get("spilled"):
        score += 5
    return {
        "kind": kind,
        "description": description,
        "edit_sketch": edit_sketch,
        "target_offset_objective": dict(objective),
        "rank_basis": [
            (
                "final-only-stack-home"
                if target.get("site_kind") == "final-only-stack-home"
                else "stack-home"
            ),
            _class_name(target.get("register_class")),
            "target-offset-before-overall-score",
        ],
        "_score": score,
    }


def _target_offset_objective(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_offset": target.get("current_offset"),
        "expected_offset": target.get("expected_offset"),
        "desired_delta": target.get("delta"),
        "target_movement_measured": False,
        "target_moved": None,
        "movement_score": None,
        "overall_match_percent": None,
    }


def _near_any(offset: int, anchors: list[int], window: int) -> bool:
    return not anchors or any(abs(offset - anchor) <= window for anchor in anchors)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _class_name(class_id: Any) -> str:
    class_int = _int_or_none(class_id)
    if class_int == 1:
        return "fpr"
    if class_int == 0:
        return "gpr"
    return "unknown"


def _format_offset(value: Any) -> str:
    offset = _int_or_none(value)
    if offset is None:
        return "?"
    return f"0x{offset:X}"
