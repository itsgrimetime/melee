from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .commands import validation_commands_for_target
from .models import (
    AllocatorNode,
    Blocker,
    LifetimePressureReport,
    SourceAttributionFact,
    SourceHypothesis,
    TargetPressureReport,
    ValidationCommand,
)


def attach_hypotheses(
    report: LifetimePressureReport,
    *,
    pcdump_path: str | Path | None,
    source_path: str | Path | None,
    allow_stale_pcdump: bool,
) -> LifetimePressureReport:
    freshness = report.allocator_facts.function.freshness.status
    is_stale = freshness == "stale"
    if is_stale and not allow_stale_pcdump:
        return replace(
            report,
            hypotheses=(),
            warnings=(
                *report.warnings,
                "stale pcdump suppresses source-action hypotheses",
            ),
        )

    nodes_by_class = {
        allocator_class.class_id: allocator_class.node_by_ig()
        for allocator_class in report.allocator_facts.classes
    }
    hypotheses: list[SourceHypothesis] = []
    commands: list[ValidationCommand] = list(report.validation_commands)
    command_ids_by_target: dict[tuple[int, int], tuple[str, ...]] = {}

    for target in report.targets:
        blocker_ig = _primary_blocker_ig(target)
        target_commands = validation_commands_for_target(
            function=report.function,
            pcdump_path=pcdump_path,
            source_path=source_path,
            force_phys=_force_phys_for_target(target),
            target_ig=target.ig_id,
            blocker_ig=blocker_ig,
            class_id=target.class_id,
        )
        commands.extend(target_commands)
        command_ids_by_target[(target.class_id, target.ig_id)] = tuple(
            command.id for command in target_commands
        )

        class_nodes = nodes_by_class.get(target.class_id, {})
        hypotheses.extend(
            _hypotheses_for_target(
                target,
                class_nodes=class_nodes,
                stale_line_mapping=is_stale,
                validation_command_ids=command_ids_by_target[
                    (target.class_id, target.ig_id)
                ],
            )
        )

    ranked = tuple(
        replace(hypothesis, rank=index + 1)
        for index, hypothesis in enumerate(
            sorted(hypotheses, key=_hypothesis_sort_key)
        )
    )
    return replace(
        report,
        source_attribution={"status": "ranked" if ranked else "none"},
        hypotheses=ranked,
        validation_commands=_dedupe_commands(commands),
    )


def _hypotheses_for_target(
    target: TargetPressureReport,
    *,
    class_nodes: dict[int, AllocatorNode],
    stale_line_mapping: bool,
    validation_command_ids: tuple[str, ...],
) -> tuple[SourceHypothesis, ...]:
    out: list[SourceHypothesis] = []
    for blocker in target.blockers:
        hypothesis = _hypothesis_for_blocker(
            target,
            blocker,
            class_nodes=class_nodes,
            stale_line_mapping=stale_line_mapping,
            validation_command_ids=validation_command_ids,
        )
        if hypothesis is not None:
            out.append(hypothesis)

    if target.status == "coalesced_away":
        aliases_known = bool(target.coalesce and target.coalesce.aliases)
        out.append(
            _source_hypothesis(
                target,
                action="avoid_or_reintroduce_coalescing",
                allocator_requirement=target.why_current_color,
                source_owner=_target_owner(target),
                confidence="medium" if aliases_known else "low",
                stale_line_mapping=stale_line_mapping,
                source=target.source_attribution,
                validation_command_ids=validation_command_ids,
                priority=30,
            )
        )
    elif target.status == "spilled":
        out.append(
            _source_hypothesis(
                target,
                action="reduce_pressure_before_select",
                allocator_requirement=target.why_current_color,
                source_owner=_target_owner(target),
                confidence="low",
                stale_line_mapping=stale_line_mapping,
                source=target.source_attribution,
                validation_command_ids=validation_command_ids,
                priority=40,
            )
        )

    return tuple(out)


def _hypothesis_for_blocker(
    target: TargetPressureReport,
    blocker: Blocker,
    *,
    class_nodes: dict[int, AllocatorNode],
    stale_line_mapping: bool,
    validation_command_ids: tuple[str, ...],
) -> SourceHypothesis | None:
    if blocker.kind == "expected_phys_holder" and blocker.ig_id is not None:
        holder = class_nodes.get(blocker.ig_id)
        source = None if holder is None else holder.source_attribution
        if _is_compiler_temp(source):
            action = "materialize_expression"
            confidence = "low"
        elif _has_source_owner(source):
            action = "shorten_lifetime"
            confidence = "medium"
        else:
            action = "split_or_scope_temp"
            confidence = "low"
        return _source_hypothesis(
            target,
            action=action,
            allocator_requirement=blocker.reason,
            source_owner=_blocker_owner(blocker, holder),
            confidence=confidence,
            stale_line_mapping=stale_line_mapping,
            source=source,
            validation_command_ids=validation_command_ids,
            priority=0,
        )

    if blocker.kind in {"candidate_order", "sticky_pool", "select_order"}:
        return _source_hypothesis(
            target,
            action="move_declaration_or_simplify_order",
            allocator_requirement=blocker.reason,
            source_owner=_target_owner(target),
            confidence="low",
            stale_line_mapping=stale_line_mapping,
            source=target.source_attribution,
            validation_command_ids=validation_command_ids,
            priority=20,
        )

    return None


def _source_hypothesis(
    target: TargetPressureReport,
    *,
    action: str,
    allocator_requirement: str,
    source_owner: str,
    confidence: str,
    stale_line_mapping: bool,
    source: SourceAttributionFact | None,
    validation_command_ids: tuple[str, ...],
    priority: int,
) -> SourceHypothesis:
    return SourceHypothesis(
        id=f"{target.class_id}-{target.ig_id}-{priority}-{action}",
        target_ig_id=target.ig_id,
        rank=0,
        action=action,
        allocator_requirement=allocator_requirement,
        source_owner=source_owner,
        confidence=confidence,
        validation_command_ids=validation_command_ids,
        line_mapping_status=_line_mapping_status(
            source,
            stale_line_mapping=stale_line_mapping,
        ),
    )


def _primary_blocker_ig(target: TargetPressureReport) -> int | None:
    for blocker in target.blockers:
        if blocker.ig_id is not None:
            return blocker.ig_id
    return None


def _force_phys_for_target(target: TargetPressureReport) -> str:
    prefix = "f" if target.class_id == 1 else ""
    return f"{prefix}{target.ig_id}:{target.expected_phys}"


def _blocker_owner(blocker: Blocker, holder: AllocatorNode | None) -> str:
    if holder is not None:
        owner = _source_owner(holder.source_attribution)
        if owner != "source unavailable":
            return owner
    if blocker.source_summary:
        return blocker.source_summary
    if blocker.ig_id is not None:
        return f"IG {blocker.ig_id}"
    return "source unavailable"


def _target_owner(target: TargetPressureReport) -> str:
    return _source_owner(target.source_attribution)


def _source_owner(source: SourceAttributionFact | None) -> str:
    if source is None:
        return "source unavailable"
    owner = source.symbol or source.expression or source.kind
    if owner is None:
        return "source unavailable"
    if source.line is not None:
        return f"{owner}:{source.line}"
    return owner


def _line_mapping_status(
    source: SourceAttributionFact | None,
    *,
    stale_line_mapping: bool,
) -> str:
    if source is None or source.line is None:
        return "not_line_specific"
    return "stale_line_mapping" if stale_line_mapping else "fresh"


def _is_compiler_temp(source: SourceAttributionFact | None) -> bool:
    return bool(
        source is not None
        and (
            source.compiler_temp
            or source.kind in {"compiler-temp", "temporary"}
        )
    )


def _has_source_owner(source: SourceAttributionFact | None) -> bool:
    return bool(
        source is not None
        and source.status in {"attributed", "available", "ambiguous"}
        and (source.symbol or source.expression or source.kind or source.line)
    )


def _hypothesis_sort_key(hypothesis: SourceHypothesis) -> tuple[int, int, str]:
    action_priority = {
        "shorten_lifetime": 0,
        "split_or_scope_temp": 1,
        "materialize_expression": 2,
        "avoid_materializing_compiler_temp": 2,
        "move_declaration_or_simplify_order": 3,
        "avoid_or_reintroduce_coalescing": 4,
        "reduce_pressure_before_select": 5,
    }
    confidence_priority = {"high": 0, "medium": 1, "low": 2}
    return (
        action_priority.get(hypothesis.action, 99),
        confidence_priority.get(hypothesis.confidence, 99),
        hypothesis.id,
    )


def _dedupe_commands(commands: list[ValidationCommand]) -> tuple[ValidationCommand, ...]:
    seen: set[str] = set()
    out: list[ValidationCommand] = []
    for command in commands:
        if command.id in seen:
            continue
        seen.add(command.id)
        out.append(command)
    return tuple(out)


__all__ = ["attach_hypotheses"]
