from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import (
    AllocatorClassFacts,
    AllocatorFacts,
    AllocatorNode,
    Blocker,
    CoalesceFacts,
    ColorDecision,
    LifetimePressureReport,
    SpillFacts,
    TargetAllocation,
    TargetPressureReport,
    TargetSet,
    ValidationCommand,
)


SCHEMA_VERSION = "lifetime-pressure-report.v1"


def analyze_lifetime_pressure(
    facts: AllocatorFacts,
    target_set: TargetSet | None,
    *,
    allow_stale_pcdump: bool = False,
) -> LifetimePressureReport:
    warnings: list[str] = []

    if facts.function.freshness.status != "fresh" and not allow_stale_pcdump:
        warnings.append(f"allocator facts freshness is {facts.function.freshness.status}")

    if target_set is None:
        return LifetimePressureReport(
            schema_version=SCHEMA_VERSION,
            function=facts.function.name,
            inventory_only=True,
            inputs={"target_set": None},
            targets=(),
            allocator_facts=facts,
            blockers=(),
            source_attribution={"status": "inventory_only"},
            hypotheses=(),
            validation_commands=(
                ValidationCommand(
                    id="derive-target",
                    purpose="derive a target from allocator facts",
                    command=(
                        "melee-agent debug target derive "
                        f"-f {facts.function.name}  # derive a target"
                    ),
                ),
            ),
            warnings=tuple(warnings),
        )

    if target_set.function is not None and target_set.function != facts.function.name:
        raise ValueError(
            "target function mismatch: "
            f"{target_set.function} != {facts.function.name}"
        )

    classes = facts.class_by_id()
    target_reports: list[TargetPressureReport] = []
    all_blockers: list[Blocker] = []
    for target in target_set.targets:
        allocator_class = classes.get(target.class_id)
        if allocator_class is None:
            warnings.append(f"requested class {target.class_id} missing")
            report = _abstained_target_report(target)
        else:
            report = _analyze_target(allocator_class, target)
        target_reports.append(report)
        all_blockers.extend(report.blockers)

    return LifetimePressureReport(
        schema_version=SCHEMA_VERSION,
        function=facts.function.name,
        inventory_only=False,
        inputs={"target_set": target_set.to_dict()},
        targets=tuple(target_reports),
        allocator_facts=facts,
        blockers=_sort_blockers(all_blockers),
        source_attribution={"status": "not_ranked"},
        hypotheses=(),
        validation_commands=(),
        warnings=tuple(warnings),
    )


def _analyze_target(
    allocator_class: AllocatorClassFacts,
    target: TargetAllocation,
) -> TargetPressureReport:
    nodes = allocator_class.node_by_ig()
    node = nodes.get(target.ig_id)
    decision = allocator_class.decision_by_ig().get(target.ig_id)
    coalesce = _coalesce_for_target(allocator_class, target.ig_id, node)
    current_phys = _current_phys(node, coalesce, nodes)

    if _is_coalesced_away(allocator_class, target.ig_id, node):
        return _target_report(
            target,
            node,
            current_phys=current_phys,
            status="coalesced_away",
            blockers=(),
            why_current_color=_coalesced_reason(target.ig_id, coalesce),
            must_change=("split coalesced alias before forcing a distinct phys",),
            confidence=_confidence(node, decision),
            coalesce=coalesce,
        )

    if node is not None and node.spill.spilled:
        return _target_report(
            target,
            node,
            current_phys=current_phys,
            status="spilled",
            blockers=(),
            why_current_color=node.spill.reason or "target was spilled before coloring",
            must_change=("keep the target live range colorable before forcing phys",),
            confidence=_confidence(node, decision),
            coalesce=coalesce,
        )

    if current_phys == target.expected_phys:
        return _target_report(
            target,
            node,
            current_phys=current_phys,
            status="no_pressure_issue",
            blockers=(),
            why_current_color=f"IG {target.ig_id} already has r{target.expected_phys}",
            must_change=(),
            confidence=_confidence(node, decision),
            coalesce=coalesce,
        )

    blockers = _target_blockers(allocator_class, target, node, decision)
    return _target_report(
        target,
        node,
        current_phys=current_phys,
        status="blocked" if blockers else "unexplained",
        blockers=blockers,
        why_current_color=_why_current_color(current_phys, decision),
        must_change=_must_change(target, blockers),
        confidence=_confidence(node, decision),
        coalesce=coalesce,
    )


def _target_blockers(
    allocator_class: AllocatorClassFacts,
    target: TargetAllocation,
    node: AllocatorNode | None,
    decision: ColorDecision | None,
) -> tuple[Blocker, ...]:
    blockers = list(_expected_phys_holders(allocator_class, target, decision))
    if blockers:
        return _sort_blockers(blockers)

    if _decision_incomplete(node, decision):
        return (
            Blocker(
                target_ig_id=target.ig_id,
                ig_id=None,
                kind="incomplete_allocator_state",
                assigned_phys=None,
                impact=80,
                reason="allocator state is incomplete, so expected-phys interference is not fully known",
                confidence="synthesized",
            ),
        )

    if decision is None:
        return ()

    blockers.extend(_order_blockers(target, decision))
    return _sort_blockers(blockers)


def _expected_phys_holders(
    allocator_class: AllocatorClassFacts,
    target: TargetAllocation,
    decision: ColorDecision | None,
) -> Iterable[Blocker]:
    nodes = allocator_class.node_by_ig()
    yielded: set[int] = set()

    if decision is not None:
        for candidate in decision.blocked_candidates:
            if candidate.phys != target.expected_phys or candidate.holder_ig_id is None:
                continue
            yielded.add(candidate.holder_ig_id)
            yield Blocker(
                target_ig_id=target.ig_id,
                ig_id=candidate.holder_ig_id,
                kind="expected_phys_holder",
                assigned_phys=candidate.holder_assigned_phys,
                impact=100,
                reason=(
                    f"expected phys r{target.expected_phys} is held by "
                    f"interfering IG {candidate.holder_ig_id}"
                ),
                source_summary=_source_summary(nodes.get(candidate.holder_ig_id)),
            )

    for edge in allocator_class.edges:
        holder_ig = None
        if edge.a == target.ig_id:
            holder_ig = edge.b
        elif edge.b == target.ig_id:
            holder_ig = edge.a
        if holder_ig is None or holder_ig in yielded:
            continue
        holder = nodes.get(holder_ig)
        if holder is None or holder.assigned_phys != target.expected_phys:
            continue
        yield Blocker(
            target_ig_id=target.ig_id,
            ig_id=holder_ig,
            kind="expected_phys_holder",
            assigned_phys=holder.assigned_phys,
            impact=100,
            reason=(
                f"expected phys r{target.expected_phys} is held by "
                f"interfering IG {holder_ig}"
            ),
            source_summary=_source_summary(holder),
        )


def _order_blockers(
    target: TargetAllocation,
    decision: ColorDecision,
) -> Iterable[Blocker]:
    if (
        target.expected_phys not in decision.candidate_phys_ordered
        and decision.candidate_phys_ordered
    ):
        yield Blocker(
            target_ig_id=target.ig_id,
            ig_id=None,
            kind="candidate_order",
            assigned_phys=decision.assigned_phys,
            impact=60,
            reason=f"expected phys r{target.expected_phys} is absent from candidate order",
            confidence=decision.confidence,
        )

    if decision.chosen_source and decision.chosen_source not in {"observed", "candidate"}:
        yield Blocker(
            target_ig_id=target.ig_id,
            ig_id=None,
            kind="sticky_pool",
            assigned_phys=decision.assigned_phys,
            impact=50,
            reason=f"chosen source {decision.chosen_source!r} selected r{decision.assigned_phys}",
            confidence=decision.confidence,
        )


def _target_report(
    target: TargetAllocation,
    node: AllocatorNode | None,
    *,
    current_phys: int | None,
    status: str,
    blockers: tuple[Blocker, ...],
    why_current_color: str,
    must_change: tuple[str, ...],
    confidence: str,
    coalesce: CoalesceFacts | None = None,
) -> TargetPressureReport:
    return TargetPressureReport(
        class_id=target.class_id,
        ig_id=target.ig_id,
        virtual=_virtual(node, target),
        current_phys=current_phys,
        expected_phys=target.expected_phys,
        status=status,
        first_def=None if node is None else node.first_def,
        source_attribution=None if node is None else node.source_attribution,
        live=None if node is None else node.live,
        simplify_order=None if node is None else node.simplify_order,
        select_order=None if node is None else node.select_order,
        coalesce=coalesce if coalesce is not None else None if node is None else node.coalesce,
        spill=None if node is None else node.spill,
        blockers=blockers,
        why_current_color=why_current_color,
        must_change=must_change,
        confidence=confidence,
    )


def _abstained_target_report(target: TargetAllocation) -> TargetPressureReport:
    return TargetPressureReport(
        class_id=target.class_id,
        ig_id=target.ig_id,
        virtual={"kind": "unknown", "number": target.ig_id},
        current_phys=None,
        expected_phys=target.expected_phys,
        status="abstained",
        first_def=None,
        source_attribution=None,
        live=None,
        simplify_order=None,
        select_order=None,
        coalesce=None,
        spill=SpillFacts(spilled=False),
        blockers=(),
        why_current_color=f"requested class {target.class_id} missing",
        must_change=(),
        confidence="unavailable",
    )


def _coalesce_for_target(
    allocator_class: AllocatorClassFacts,
    ig_id: int,
    node: AllocatorNode | None,
) -> CoalesceFacts | None:
    if node is not None:
        return node.coalesce
    for alias, root in allocator_class.coalesce_mappings:
        if alias == ig_id:
            return CoalesceFacts(root_ig_id=root, aliases=(alias,))
    for mapping in allocator_class.coalesce.get("mappings", ()):
        if not isinstance(mapping, dict) or int(mapping.get("alias", -1)) != ig_id:
            continue
        return CoalesceFacts(root_ig_id=int(mapping["root"]), aliases=(ig_id,))
    return None


def _is_coalesced_away(
    allocator_class: AllocatorClassFacts,
    ig_id: int,
    node: AllocatorNode | None,
) -> bool:
    if node is not None and node.color_status == "coalesced_alias":
        return True
    return _coalesce_for_target(allocator_class, ig_id, node) is not None and node is None


def _current_phys(
    node: AllocatorNode | None,
    coalesce: CoalesceFacts | None,
    nodes: dict[int, AllocatorNode],
) -> int | None:
    if node is not None and node.assigned_phys is not None:
        return node.assigned_phys
    root = None if coalesce is None else coalesce.root_ig_id
    if root is None:
        return None
    root_node = nodes.get(root)
    return None if root_node is None else root_node.assigned_phys


def _decision_incomplete(
    node: AllocatorNode | None,
    decision: ColorDecision | None,
) -> bool:
    if node is not None and "incomplete_interferers" in node.flags:
        return True
    if decision is None:
        return node is None
    return decision.confidence not in {"observed", "exact"}


def _must_change(
    target: TargetAllocation,
    blockers: tuple[Blocker, ...],
) -> tuple[str, ...]:
    if not blockers:
        return ()
    first = blockers[0]
    if first.kind == "expected_phys_holder" and first.ig_id is not None:
        return (
            "remove interference or move "
            f"IG {first.ig_id} off r{target.expected_phys} before coloring IG {target.ig_id}",
        )
    if first.kind == "incomplete_allocator_state":
        return ("collect complete allocator state before ranking pressure blockers",)
    return (first.reason,)


def _sort_blockers(blockers: Iterable[Blocker]) -> tuple[Blocker, ...]:
    return tuple(
        sorted(
            blockers,
            key=lambda blocker: (
                -blocker.impact,
                blocker.ig_id is None,
                -1 if blocker.ig_id is None else blocker.ig_id,
            ),
        )
    )


def _virtual(node: AllocatorNode | None, target: TargetAllocation) -> dict[str, Any]:
    if node is None:
        return {"kind": "unknown", "number": target.ig_id}
    return {"kind": node.virtual_kind, "number": node.virtual_number}


def _source_summary(node: AllocatorNode | None) -> str | None:
    if node is None:
        return None
    source = node.source_attribution
    parts = [
        value
        for value in (source.symbol, source.expression, source.kind)
        if value is not None
    ]
    return " / ".join(parts) if parts else source.status


def _confidence(node: AllocatorNode | None, decision: ColorDecision | None) -> str:
    if decision is not None:
        return decision.confidence
    if node is not None:
        return node.source_attribution.confidence
    return "unavailable"


def _why_current_color(
    current_phys: int | None,
    decision: ColorDecision | None,
) -> str:
    if decision is None:
        return "no color decision was available"
    if current_phys is None:
        return "color decision did not assign a physical register"
    return f"{decision.decision_rule} selected r{current_phys} from {decision.chosen_source}"


def _coalesced_reason(ig_id: int, coalesce: CoalesceFacts | None) -> str:
    if coalesce is None or coalesce.root_ig_id is None:
        return f"IG {ig_id} was coalesced away"
    return f"IG {ig_id} was coalesced into IG {coalesce.root_ig_id}"


__all__ = ["analyze_lifetime_pressure"]
