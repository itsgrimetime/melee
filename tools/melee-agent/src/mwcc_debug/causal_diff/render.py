"""Stable human and JSON rendering for causal-difference reports."""

from __future__ import annotations

import json
from typing import Mapping

from .inference import CausalDiffReport, CausalVerdict


def render_json(report: CausalDiffReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"


def _delta_text(delta: Mapping[str, object]) -> str:
    ordered = ((key, delta[key]) for key in sorted(delta) if key not in {"effect_id"})
    return ", ".join(f"{key}={value}" for key, value in ordered)


def render_verdict_lines(verdict: CausalVerdict) -> list[str]:
    label = verdict.status.value.replace("-", " ").upper()
    cause = "none" if verdict.cause is None else verdict.cause.record_id
    lines = [f"{label}: {verdict.pair_id}", f"  cause: {cause}"]
    if verdict.proof_paths:
        shortest = min(verdict.proof_paths, key=lambda path: (len(path), path))
        lines.append("  shortest path: " + " -> ".join(shortest))
    else:
        lines.append("  shortest path: none")
    lines.extend(
        (
            f"  allocator: {_delta_text(verdict.allocator_delta)}",
            f"  stack: {_delta_text(verdict.stack_delta)}",
        )
    )
    if verdict.failed_gates:
        lines.append("  failed gates: " + ", ".join(verdict.failed_gates))
    if verdict.rejected_alternatives:
        lines.append("  rejected alternatives: " + ", ".join(verdict.rejected_alternatives))
    lines.append(f"  recommendation: {verdict.recommendation}")
    lines.append("  commands:")
    lines.extend(f"    {command}" for command in verdict.follow_up_commands)
    return lines


def render_missing_and_warning_lines(report: CausalDiffReport) -> list[str]:
    lines: list[str] = []
    if report.missing_evidence:
        lines.append("missing evidence: " + ", ".join(report.missing_evidence))
    if report.warnings:
        lines.append("warnings: " + ", ".join(report.warnings))
    return lines


def render_text(report: CausalDiffReport) -> str:
    lines = [
        f"causal-diff - {report.function}",
        f"status: {report.analysis_status.value}",
    ]
    for verdict in report.verdicts:
        lines.extend(render_verdict_lines(verdict))
    lines.extend(render_missing_and_warning_lines(report))
    return "\n".join(lines) + "\n"


__all__ = ["render_json", "render_text"]
