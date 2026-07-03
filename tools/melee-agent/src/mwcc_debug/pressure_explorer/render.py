from __future__ import annotations

import csv
import io
from typing import Any

from .models import Blocker, LifetimePressureReport, TargetPressureReport


def render_json_report(report: LifetimePressureReport) -> dict[str, object]:
    return report.to_dict()


def render_text_report(report: LifetimePressureReport) -> str:
    lines: list[str] = []
    _section(lines, f"LIFETIME PRESSURE - {report.function.upper()}")
    lines.append(f"schema: {report.schema_version}")
    lines.append(f"mode: {'inventory-only' if report.inventory_only else 'targeted'}")
    lines.append("")

    _section(lines, "INPUTS")
    if report.inventory_only:
        lines.append("inventory-only: no target allocation supplied")
    else:
        target_set = report.inputs.get("target_set")
        lines.append(f"target_set: {_compact_value(target_set)}")
    lines.append("")

    _section(lines, "TARGET SUMMARY")
    if report.targets:
        for target in report.targets:
            lines.extend(_target_summary_lines(target))
    else:
        lines.append("no targets")
    lines.append("")

    _section(lines, "ALLOCATOR FACTS")
    lines.extend(_allocator_fact_lines(report))
    lines.append("")

    _section(lines, "BLOCKERS")
    if report.inventory_only:
        lines.append("inventory-only: no target allocation supplied")
    elif any(target.blockers for target in report.targets):
        for target in report.targets:
            for blocker in target.blockers:
                lines.extend(_blocker_lines(target, blocker))
    elif report.blockers:
        for blocker in report.blockers:
            lines.append(
                "  "
                f"target IG {blocker.target_ig_id}: "
                f"{blocker.kind} via {_ig_label(blocker.ig_id)} "
                f"impact={blocker.impact} confidence={blocker.confidence}"
            )
            lines.append(f"    {blocker.reason}")
            if blocker.source_summary:
                lines.append(f"    source: {blocker.source_summary}")
    else:
        lines.append("none")
    lines.append("")

    _section(lines, "SOURCE GUESSES")
    lines.append(f"status: {report.source_attribution.get('status', 'unknown')}")
    if report.hypotheses:
        owners = sorted({hypothesis.source_owner for hypothesis in report.hypotheses})
        for owner in owners:
            lines.append(f"  {owner}")
    else:
        lines.append("none")
    lines.append("")

    _section(lines, "HYPOTHESES")
    if report.hypotheses:
        for hypothesis in report.hypotheses:
            lines.append(
                "  "
                f"{hypothesis.rank}. {hypothesis.action} "
                f"for IG {hypothesis.target_ig_id} "
                f"confidence={hypothesis.confidence}"
            )
            lines.append(f"    requires: {hypothesis.allocator_requirement}")
            lines.append(f"    owner: {hypothesis.source_owner}")
    else:
        lines.append("none")
    lines.append("")

    _section(lines, "VALIDATION COMMANDS")
    if report.validation_commands:
        for command in report.validation_commands:
            lines.append(f"  {command.id}: {command.purpose}")
            lines.append(f"    {command.command}")
    else:
        lines.append("none")
    lines.append("")

    _section(lines, "CANDIDATE COMPARISONS")
    if report.candidate_comparisons:
        for comparison in report.candidate_comparisons:
            lines.extend(_candidate_comparison_lines(comparison))
    else:
        lines.append("none")
    lines.append("")

    _section(lines, "WARNINGS")
    if report.warnings:
        lines.extend(f"  {warning}" for warning in report.warnings)
    else:
        lines.append("none")

    return "\n".join(lines).rstrip() + "\n"


def render_dot(report: LifetimePressureReport) -> str:
    lines = [
        "digraph lifetime_pressure {",
        "  rankdir=LR;",
        f"  label=\"{_dot_escape(report.function)}\";",
    ]
    for target in report.targets:
        target_id = _dot_node_id(target.class_id, target.ig_id)
        target_label = (
            f"target c{target.class_id} IG {target.ig_id}\n"
            f"status {target.status}\n"
            f"expected {_phys_label(target.expected_phys, target.class_id)}"
        )
        lines.append(
            f"  {target_id} [shape=box,label=\"{_dot_escape(target_label)}\"];"
        )
        for blocker in target.blockers:
            if blocker.ig_id is None:
                blocker_id = (
                    f"c{target.class_id}_blocker_{target.ig_id}_"
                    f"{_dot_safe_name(blocker.kind)}"
                )
                blocker_label = f"{blocker.kind}\nimpact {blocker.impact}"
            else:
                blocker_id = _dot_node_id(target.class_id, blocker.ig_id)
                blocker_label = (
                    f"blocker c{target.class_id} IG {blocker.ig_id}\n"
                    f"{blocker.kind}\n"
                    f"{_phys_label(blocker.assigned_phys, target.class_id)}"
                )
            lines.append(
                f"  {blocker_id} [label=\"{_dot_escape(blocker_label)}\"];"
            )
            edge_label = f"{blocker.kind}\nimpact {blocker.impact}"
            lines.append(
                f"  {blocker_id} -> {target_id} "
                f"[label=\"{_dot_escape(edge_label)}\"];"
            )
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_blocker_table_csv(report: LifetimePressureReport) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_BLOCKER_TABLE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(_csv_blocker_row(row) for row in render_blocker_table_json(report))
    return output.getvalue()


def render_blocker_table_json(
    report: LifetimePressureReport,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for target in report.targets:
        rows.extend(_blocker_row(target, blocker) for blocker in target.blockers)
    if rows:
        return rows
    return [_blocker_row(None, blocker) for blocker in report.blockers]


_BLOCKER_TABLE_FIELDS = (
    "target_ig",
    "blocker_ig",
    "target_class",
    "blocker_class",
    "kind",
    "assigned_phys",
    "impact",
    "reason",
    "source_summary",
    "confidence",
)


def _section(lines: list[str], title: str) -> None:
    lines.append(title)


def _target_summary_lines(target: TargetPressureReport) -> list[str]:
    return [
        "  "
        f"IG {target.ig_id} class={target.class_id} "
        f"status={target.status} "
        f"current={_phys_label(target.current_phys, target.class_id)} "
        f"expected={_phys_label(target.expected_phys, target.class_id)}",
        f"    why: {target.why_current_color}",
        f"    must_change: {_tuple_text(target.must_change)}",
    ]


def _allocator_fact_lines(report: LifetimePressureReport) -> list[str]:
    facts = report.allocator_facts
    lines = [
        f"function: {facts.function.name}",
        f"freshness: {facts.function.freshness.status}",
    ]
    for allocator_class in facts.classes:
        lines.append(
            "  "
            f"class {allocator_class.class_id} ({allocator_class.class_name}): "
            f"nodes={len(allocator_class.nodes)} "
            f"edges={len(allocator_class.edges)} "
            f"decisions={len(allocator_class.color_decisions)}"
        )
    return lines


def _candidate_comparison_lines(comparison: Any) -> list[str]:
    label = _field(comparison, "label", "candidate")
    status = _field(comparison, "status", "unknown")
    identity_status = _field(comparison, "identity_status", "unknown")
    path = _field(comparison, "path", "")
    return [
        f"  {label}: status={status} identity={identity_status}",
        f"    path: {path}",
    ]


def _blocker_lines(target: TargetPressureReport, blocker: Blocker) -> list[str]:
    lines = [
        "  "
        f"target c{target.class_id} IG {blocker.target_ig_id}: "
        f"{blocker.kind} via {_ig_label(blocker.ig_id)} "
        f"impact={blocker.impact} confidence={blocker.confidence}",
        f"    {blocker.reason}",
    ]
    if blocker.source_summary:
        lines.append(f"    source: {blocker.source_summary}")
    return lines


def _blocker_row(
    target: TargetPressureReport | None,
    blocker: Blocker,
) -> dict[str, object]:
    target_class = None if target is None else target.class_id
    return {
        "target_ig": blocker.target_ig_id,
        "blocker_ig": blocker.ig_id,
        "target_class": target_class,
        "blocker_class": None if blocker.ig_id is None else target_class,
        "kind": blocker.kind,
        "assigned_phys": blocker.assigned_phys,
        "impact": blocker.impact,
        "reason": blocker.reason,
        "source_summary": blocker.source_summary,
        "confidence": blocker.confidence,
    }


def _csv_blocker_row(row: dict[str, object]) -> dict[str, object]:
    return {field: "" if row[field] is None else row[field] for field in _BLOCKER_TABLE_FIELDS}


def _compact_value(value: object) -> str:
    if value is None:
        return "none"
    return str(value)


def _tuple_text(values: tuple[str, ...]) -> str:
    return "; ".join(values) if values else "none"


def _phys_label(phys: int | None, class_id: int) -> str:
    if phys is None:
        return "none"
    prefix = "f" if class_id == 1 else "r"
    return f"{prefix}{phys}"


def _ig_label(ig_id: int | None) -> str:
    return "allocator state" if ig_id is None else f"IG {ig_id}"


def _field(value: Any, name: str, default: object) -> object:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _dot_node_id(class_id: int, ig_id: int) -> str:
    return f"c{class_id}_ig{ig_id}"


def _dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def _dot_safe_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in value)
    return out or "unknown"


__all__ = [
    "render_json_report",
    "render_text_report",
    "render_dot",
    "render_blocker_table_csv",
    "render_blocker_table_json",
]
