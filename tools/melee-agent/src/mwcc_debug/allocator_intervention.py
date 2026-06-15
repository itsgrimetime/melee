"""Reports for backend-backed allocator interventions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .colorgraph_parser import FunctionEvents, find_function, parse_hook_events
from .diff_report import DiffReport, compare_function_dumps


@dataclass(frozen=True)
class CoalesceInterventionSpec:
    action: str
    virt: int
    root: int
    class_id: int = 0

    @property
    def backend_value(self) -> str:
        if self.action == "block":
            return f"{self.virt}={self.virt}"
        if self.action == "force":
            return f"{self.virt}={self.root}"
        raise ValueError(f"unsupported coalesce intervention action: {self.action}")

    @property
    def backend_env(self) -> dict[str, str]:
        return {"MWCC_DEBUG_FORCE_COALESCE": self.backend_value}


@dataclass(frozen=True)
class CoalesceInterventionReport:
    function: str
    spec: CoalesceInterventionSpec
    backend_env: dict[str, str]
    backend_applied: bool
    target_reached: bool
    prevention: str | None
    baseline_pair_root: int | None
    intervention_pair_root: int | None
    final_allocation_changed: bool
    simplify_order_changed: bool
    coalesce_mappings_changed: bool
    spill_set_changed: bool
    baseline_match_percent: float | None = None
    intervention_match_percent: float | None = None
    first_divergence_pass: str | None = None
    first_divergence_summary: str | None = None
    first_divergence_kind: str | None = None

    @property
    def match_score_changed(self) -> bool | None:
        if self.baseline_match_percent is None or self.intervention_match_percent is None:
            return None
        return abs(self.baseline_match_percent - self.intervention_match_percent) > 0.00001

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "hook": "coalesce",
            "action": self.spec.action,
            "virt": self.spec.virt,
            "root": self.spec.root,
            "class_id": self.spec.class_id,
            "backend_env": self.backend_env,
            "backend_applied": self.backend_applied,
            "target_reached": self.target_reached,
            "prevention": self.prevention,
            "baseline_pair_root": self.baseline_pair_root,
            "intervention_pair_root": self.intervention_pair_root,
            "final_allocation_changed": self.final_allocation_changed,
            "simplify_order_changed": self.simplify_order_changed,
            "coalesce_mappings_changed": self.coalesce_mappings_changed,
            "spill_set_changed": self.spill_set_changed,
            "baseline_match_percent": self.baseline_match_percent,
            "intervention_match_percent": self.intervention_match_percent,
            "match_score_changed": self.match_score_changed,
            "first_divergence_pass": self.first_divergence_pass,
            "first_divergence_summary": self.first_divergence_summary,
            "first_divergence_kind": self.first_divergence_kind,
        }


def parse_coalesce_pair(raw: str) -> tuple[int, int]:
    left, sep, right = raw.strip().partition("=")
    if sep != "=" or not left.strip() or not right.strip():
        raise ValueError(f"invalid coalesce pair {raw!r}; expected rV=rRoot")
    return (_parse_virtual(left), _parse_virtual(right))


def _parse_virtual(raw: str) -> int:
    stripped = raw.strip()
    if stripped.lower().startswith("r"):
        stripped = stripped[1:]
    value = int(stripped)
    if value < 0:
        raise ValueError(f"invalid negative virtual: {raw!r}")
    return value


def analyze_coalesce_intervention(
    baseline_text: str,
    intervention_text: str,
    *,
    function: str,
    spec: CoalesceInterventionSpec,
    baseline_match_percent: float | None = None,
    intervention_match_percent: float | None = None,
) -> CoalesceInterventionReport:
    baseline_events = _require_function_events(baseline_text, function, "baseline")
    intervention_events = _require_function_events(
        intervention_text,
        function,
        "intervention",
    )
    baseline_aliases = _final_alias_map(baseline_events, spec.class_id)
    intervention_aliases = _final_alias_map(intervention_events, spec.class_id)
    baseline_pair_root = baseline_aliases.get(spec.virt)
    intervention_pair_root = intervention_aliases.get(spec.virt)
    backend_applied = _backend_applied(intervention_events, spec)

    if spec.action == "block":
        target_reached = intervention_pair_root != spec.root
    elif spec.action == "force":
        target_reached = intervention_pair_root == spec.root
    else:
        raise ValueError(f"unsupported coalesce intervention action: {spec.action}")

    first_divergence = _safe_diff_report(
        baseline_text,
        intervention_text,
        function=function,
    )
    earliest = first_divergence.earliest if first_divergence is not None else None

    return CoalesceInterventionReport(
        function=function,
        spec=spec,
        backend_env=spec.backend_env,
        backend_applied=backend_applied,
        target_reached=target_reached,
        prevention=_prevention_summary(
            spec=spec,
            backend_applied=backend_applied,
            target_reached=target_reached,
            intervention_pair_root=intervention_pair_root,
        ),
        baseline_pair_root=baseline_pair_root,
        intervention_pair_root=intervention_pair_root,
        final_allocation_changed=(
            _allocation_signature(baseline_events, spec.class_id)
            != _allocation_signature(intervention_events, spec.class_id)
        ),
        simplify_order_changed=(
            _simplify_order(baseline_events, spec.class_id)
            != _simplify_order(intervention_events, spec.class_id)
        ),
        coalesce_mappings_changed=baseline_aliases != intervention_aliases,
        spill_set_changed=(
            _spill_set(baseline_events, spec.class_id)
            != _spill_set(intervention_events, spec.class_id)
        ),
        baseline_match_percent=baseline_match_percent,
        intervention_match_percent=intervention_match_percent,
        first_divergence_pass=earliest.pass_name if earliest is not None else None,
        first_divergence_summary=earliest.summary if earliest is not None else None,
        first_divergence_kind=earliest.kind.value if earliest is not None and earliest.kind else None,
    )


def render_coalesce_intervention_text(report: CoalesceInterventionReport) -> str:
    spec = report.spec
    lines = [
        f"allocator-intervention coalesce - {report.function}",
        f"hook: {spec.action} r{spec.virt} -> r{spec.root}",
        "backend env: "
        + " ".join(f"{key}={value}" for key, value in report.backend_env.items()),
        f"backend applied: {_yes_no(report.backend_applied)}",
        f"target reached: {_yes_no(report.target_reached)}",
        (
            "pair state: "
            f"baseline {_fmt_pair_root(spec.virt, report.baseline_pair_root)}; "
            f"intervention {_fmt_pair_root(spec.virt, report.intervention_pair_root)}"
        ),
    ]
    if report.prevention is not None:
        lines.append(f"prevention: {report.prevention}")
    if report.first_divergence_pass is None:
        lines.append("first divergence: none")
    else:
        detail = report.first_divergence_summary or "changed"
        kind = f" [{report.first_divergence_kind}]" if report.first_divergence_kind else ""
        lines.append(
            f"first divergence: {report.first_divergence_pass}{kind}: {detail}"
        )
    lines.extend([
        "changed:",
        f"  final allocation: {_yes_no(report.final_allocation_changed)}",
        f"  simplify order: {_yes_no(report.simplify_order_changed)}",
        f"  coalesce mappings changed: {_yes_no(report.coalesce_mappings_changed)}",
        f"  spill set: {_yes_no(report.spill_set_changed)}",
        f"  real match score changed: {_fmt_score_change(report)}",
    ])
    return "\n".join(lines)


def _require_function_events(text: str, function: str, label: str) -> FunctionEvents:
    events = find_function(parse_hook_events(text), function)
    if events is None:
        raise ValueError(f"{label} pcdump has no hook events for {function}")
    return events


def _final_alias_map(events: FunctionEvents, class_id: int) -> dict[int, int]:
    aliases: dict[int, int] = {}
    for section in events.coalesced_alias_sections:
        if section.class_id != class_id:
            continue
        aliases = {alias: root for alias, root, _phys in section.aliases}
    return aliases


def _backend_applied(events: FunctionEvents, spec: CoalesceInterventionSpec) -> bool:
    desired_root = spec.virt if spec.action == "block" else spec.root
    for section in events.coalesce_sections:
        if section.class_id != spec.class_id:
            continue
        for virt, _old, new in section.forced_overrides:
            if virt == spec.virt and new == desired_root:
                return True
    return False


def _allocation_signature(events: FunctionEvents, class_id: int) -> tuple[tuple[int, int], ...]:
    decisions = []
    for section in events.colorgraph_sections:
        if section.class_id != class_id:
            continue
        decisions = [
            (decision.ig_idx, decision.assigned_reg)
            for decision in section.decisions
            if decision.ig_idx >= 0
        ]
    return tuple(sorted(decisions))


def _simplify_order(events: FunctionEvents, class_id: int) -> tuple[int, ...]:
    order = ()
    for section in events.simplify_sections:
        if section.class_id == class_id:
            order = tuple(entry.ig_idx for entry in section.entries if entry.ig_idx >= 0)
    return order


def _spill_set(events: FunctionEvents, class_id: int) -> frozenset[int]:
    spilled: set[int] = set()
    for section in events.simplify_sections:
        if section.class_id == class_id:
            spilled = {entry.ig_idx for entry in section.entries if entry.spilled}
    return frozenset(spilled)


def _safe_diff_report(
    baseline_text: str,
    intervention_text: str,
    *,
    function: str,
) -> DiffReport | None:
    try:
        return compare_function_dumps(
            baseline_text,
            intervention_text,
            function=function,
            label_a="baseline",
            label_b="intervention",
        )
    except Exception:
        return None


def _prevention_summary(
    *,
    spec: CoalesceInterventionSpec,
    backend_applied: bool,
    target_reached: bool,
    intervention_pair_root: int | None,
) -> str | None:
    if target_reached:
        return None
    if not backend_applied:
        return (
            "backend did not apply the requested override; check function scope, "
            "register class, or virtual bounds before allocator coloring"
        )
    if spec.action == "force":
        if intervention_pair_root is None:
            return (
                f"backend applied the override, but final aliases kept r{spec.virt} "
                f"independent instead of r{spec.root}"
            )
        return (
            f"backend applied the override, but final aliases map r{spec.virt} "
            f"to r{intervention_pair_root} instead of r{spec.root}"
        )
    return (
        f"backend applied the override, but final aliases still map r{spec.virt} "
        f"to blocked root r{spec.root}"
    )


def _fmt_pair_root(virt: int, root: int | None) -> str:
    if root is None:
        return f"r{virt} independent"
    return f"r{virt}->r{root}"


def _fmt_score_change(report: CoalesceInterventionReport) -> str:
    before = report.baseline_match_percent
    after = report.intervention_match_percent
    if before is None or after is None:
        return "not measured"
    return f"{_yes_no(report.match_score_changed)} ({before:.5f} -> {after:.5f})"


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"
