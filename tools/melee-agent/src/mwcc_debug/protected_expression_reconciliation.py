"""Dual-frontier protected expression/structural reconciliation.

The v1 lane is pure generation and ranking over already-retained evidence. It
does not compile, invoke ``score-source``, or mutate the repo. Callers provide
an expression-protected source/score payload, a lower-structural source/score
payload, and optionally score payloads for generated probes.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .source_hunks import (
    SourceHunk,
    apply_hunks_to_text,
    diff_line_hunks,
    hunks_overlap,
    line_ranges_overlap,
    manual_subhunks_from_source_hunks,
    split_hunks_conservatively,
)
from .source_patch import FunctionSpan, find_function


CLASS_ID = "protected-expression-structural-reconciliation"
DEFAULT_MAX_NORMALIZED_DIFF_LINES = 30
_EVIDENCE_CANDIDATE_ID_SUFFIXES = (
    ".score.json",
    "_score.json",
    ".score",
    "_score",
    ".pcdump.txt",
    ".c",
)


@dataclass(frozen=True)
class ExpressionAnchorRequirement:
    baseline_virtual: int
    expected: int
    signature: Mapping[str, Any]
    label: str | None = None
    required_status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_virtual": self.baseline_virtual,
            "expected": self.expected,
            "signature": dict(self.signature),
            "label": self.label,
            "required_status": self.required_status,
        }


@dataclass(frozen=True)
class ReconciliationFrontierSource:
    frontier_id: str
    role: str
    path: Path | None
    source_text: str
    target_function: str
    source_function: str
    score_payload: Mapping[str, Any] | None = None
    anchors: tuple[ExpressionAnchorRequirement, ...] = ()
    expression_matched: int | None = None
    expression_targeted: int | None = None
    structural_guard: Mapping[str, Any] | None = None
    normalized_diff_lines: int | None = None
    frame_size: int | None = None

    def to_summary(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "frontier_id": self.frontier_id,
            "role": self.role,
            "target_function": self.target_function,
            "source_function": self.source_function,
            "path": str(self.path) if self.path is not None else None,
            "expression_matched": self.expression_matched,
            "expression_targeted": self.expression_targeted,
            "normalized_diff_lines": self.normalized_diff_lines,
            "frame_size": self.frame_size,
        }
        if self.structural_guard is not None:
            data["structural_guard"] = dict(self.structural_guard)
        if self.anchors:
            data["anchor_count"] = len(self.anchors)
        return data


@dataclass(frozen=True)
class ReconciliationHunk:
    hunk_id: str
    parent_frontier_id: str
    base_start: int
    base_end: int
    candidate_start: int
    candidate_end: int
    removed: tuple[str, ...]
    added: tuple[str, ...]
    kind: str
    risk: str
    protected_anchor_overlap: tuple[int, ...] = ()
    structural_intent: tuple[str, ...] = ()
    source_hunk: SourceHunk | None = None

    @classmethod
    def from_source_hunk(
        cls,
        hunk: SourceHunk,
        *,
        parent_frontier_id: str,
        protected_anchor_overlap: Sequence[int] = (),
        structural_intent: Sequence[str] = (),
    ) -> "ReconciliationHunk":
        return cls(
            hunk_id=hunk.hunk_id,
            parent_frontier_id=parent_frontier_id,
            base_start=hunk.base_start,
            base_end=hunk.base_end,
            candidate_start=hunk.candidate_start,
            candidate_end=hunk.candidate_end,
            removed=hunk.removed,
            added=hunk.added,
            kind=hunk.kind,
            risk=hunk.risk,
            protected_anchor_overlap=tuple(protected_anchor_overlap),
            structural_intent=tuple(structural_intent),
            source_hunk=hunk,
        )

    def to_dict(self) -> dict[str, Any]:
        if self.source_hunk is not None:
            data = self.source_hunk.to_dict(one_based=True)
        else:
            data = {
                "hunk_id": self.hunk_id,
                "base_start": self.base_start,
                "base_end": self.base_end,
                "candidate_start": self.candidate_start,
                "candidate_end": self.candidate_end,
                "removed": list(self.removed),
                "added": list(self.added),
                "kind": self.kind,
                "risk": self.risk,
                "base_range": _one_based_range(self.base_start, self.base_end),
                "candidate_range": _one_based_range(
                    self.candidate_start,
                    self.candidate_end,
                ),
            }
        data["parent_frontier_id"] = self.parent_frontier_id
        data["protected_anchor_overlap"] = list(self.protected_anchor_overlap)
        data["structural_intent"] = list(self.structural_intent)
        return data


@dataclass(frozen=True)
class ReconciliationCandidate:
    candidate_id: str
    source_text: str
    applied_hunks: tuple[ReconciliationHunk, ...]
    provenance: Mapping[str, Any]
    score_payload: Mapping[str, Any] | None = None
    anchor_preservation: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    preserved_anchor_count: int = 0
    lost_anchor_blockers: tuple[str, ...] = ()
    normalized_diff_lines: int | None = None
    frame_improved: bool = False
    structural_improved: bool = False
    structural_guard_accepted: bool = False
    score_error: str | None = None
    score_source: Mapping[str, Any] | None = None
    path: str | None = None

    @property
    def all_anchors_preserved(self) -> bool:
        required = int(self.provenance.get("required_anchor_count") or 0)
        return (
            required > 0
            and self.preserved_anchor_count == required
            and not self.lost_anchor_blockers
        )

    @property
    def hunk_line_delta(self) -> int:
        return sum(
            len(hunk.added) - len(hunk.removed)
            for hunk in self.applied_hunks
        )

    @property
    def rank_key(self) -> tuple[Any, ...]:
        normalized = self.normalized_diff_lines
        frame_size = _int_or_none(self.provenance.get("frame_size"))
        return (
            -int(self.all_anchors_preserved),
            -int(self.structural_improved),
            -int(self.structural_guard_accepted),
            normalized if normalized is not None else 10**9,
            abs(frame_size - 168) if frame_size is not None else 10**9,
            len(self.applied_hunks),
            abs(self.hunk_line_delta),
            self.candidate_id,
        )

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "applied_hunks": [hunk.to_dict() for hunk in self.applied_hunks],
            "provenance": dict(self.provenance),
            "anchor_preservation": {
                str(key): dict(value)
                for key, value in self.anchor_preservation.items()
            },
            "preserved_anchor_count": self.preserved_anchor_count,
            "lost_anchor_blockers": list(self.lost_anchor_blockers),
            "normalized_diff_lines": self.normalized_diff_lines,
            "frame_improved": self.frame_improved,
            "structural_improved": self.structural_improved,
            "structural_guard_accepted": self.structural_guard_accepted,
        }
        if self.path is not None:
            data["path"] = self.path
        if self.score_source is not None:
            data["score_source"] = dict(self.score_source)
        if self.score_payload is not None:
            data["score_payload"] = dict(self.score_payload)
        if self.score_error is not None:
            data["score_error"] = self.score_error
        if include_source:
            data["source_text"] = self.source_text
        return data


@dataclass(frozen=True)
class ReconciliationReport:
    status: str
    class_id: str
    frontiers: Mapping[str, Any]
    anchor_requirements: tuple[ExpressionAnchorRequirement, ...]
    generated_count: int
    scored_count: int
    candidates: tuple[ReconciliationCandidate, ...]
    best_preserving_candidate: ReconciliationCandidate | None
    best_structural_candidate: ReconciliationCandidate | None
    terminal_blockers: tuple[dict[str, Any], ...]
    next_actions: tuple[str, ...]
    generation_blockers: tuple[dict[str, Any], ...] = ()

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        return {
            "status": self.status,
            "class_id": self.class_id,
            "frontiers": dict(self.frontiers),
            "anchor_requirements": [
                anchor.to_dict() for anchor in self.anchor_requirements
            ],
            "generated_count": self.generated_count,
            "scored_count": self.scored_count,
            "candidates": [
                candidate.to_dict(include_source=include_source)
                for candidate in self.candidates
            ],
            "best_preserving_candidate": (
                self.best_preserving_candidate.to_dict(include_source=include_source)
                if self.best_preserving_candidate is not None
                else None
            ),
            "best_structural_candidate": (
                self.best_structural_candidate.to_dict(include_source=include_source)
                if self.best_structural_candidate is not None
                else None
            ),
            "terminal_blockers": list(self.terminal_blockers),
            "generation_blockers": list(self.generation_blockers),
            "next_actions": list(self.next_actions),
        }


def reconcile_frontiers(
    *,
    expression_source_text: str,
    expression_score_payload: Mapping[str, Any],
    structural_source_text: str,
    structural_score_payload: Mapping[str, Any],
    target_function: str,
    source_function: str | None = None,
    expression_path: Path | None = None,
    structural_path: Path | None = None,
    max_subhunks: int = 3,
    max_candidates: int = 64,
    max_normalized_diff_lines: int = DEFAULT_MAX_NORMALIZED_DIFF_LINES,
    candidate_score_payloads: Sequence[Mapping[str, Any]] = (),
    source_hunks: Sequence[Mapping[str, Any]] = (),
) -> ReconciliationReport:
    """Generate and rank structural imports from a protected source frontier."""

    patch_function = source_function or target_function
    expression_score = _expression_score_from_payload(expression_score_payload)
    structural_score = _expression_score_from_payload(structural_score_payload)
    anchor_requirements, anchor_blockers = build_anchor_requirements(expression_score)

    expression_frontier = _frontier(
        frontier_id="expression-protected",
        role="expression-protected",
        path=expression_path,
        source_text=expression_source_text,
        target_function=target_function,
        source_function=patch_function,
        score_payload=expression_score_payload,
        anchors=anchor_requirements,
    )
    structural_frontier = _frontier(
        frontier_id="lower-structural",
        role="lower-structural",
        path=structural_path,
        source_text=structural_source_text,
        target_function=target_function,
        source_function=patch_function,
        score_payload=structural_score_payload,
        anchors=(),
        expression_score=structural_score,
    )

    function_bits = _function_pair(
        expression_source_text,
        structural_source_text,
        patch_function,
    )
    generation_blockers = list(anchor_blockers)
    if function_bits is None:
        generation_blockers.append({
            "blocker": "source-function-not-found",
            "source_function": patch_function,
            "target_function": target_function,
        })
        return _blocked_report(
            expression_frontier=expression_frontier,
            structural_frontier=structural_frontier,
            anchors=anchor_requirements,
            generation_blockers=tuple(generation_blockers),
        )

    expression_span, expression_function, structural_function = function_bits
    raw_hunks = diff_line_hunks(
        expression_function,
        structural_function,
        hunk_prefix="h",
    )
    split_plan = split_hunks_conservatively(raw_hunks)
    function_start_line = (
        expression_source_text[:expression_span.sig_start].count("\n") + 1
    )
    manual_subhunks = manual_subhunks_from_source_hunks(
        source_hunks,
        line_offset=max(0, function_start_line - 1),
    )
    raw_manual_subhunks = manual_subhunks_from_source_hunks(source_hunks)
    if raw_manual_subhunks:
        manual_subhunks = (*manual_subhunks, *raw_manual_subhunks)
    manual_parent_ids = {
        hunk.parent_hunk_id for hunk in manual_subhunks if hunk.parent_hunk_id
    }
    generation_blockers.extend(
        blocker for blocker in split_plan.blockers
        if not (
            blocker.get("blocker") == "manual-subhunk-range-required"
            and (
                blocker.get("hunk_id") in manual_parent_ids
                or _manual_subhunk_overlaps_blocker(manual_subhunks, blocker)
            )
        )
    )
    hunk_map = _reconciliation_hunks(
        (*split_plan.hunks, *manual_subhunks),
        frontier_id=structural_frontier.frontier_id,
        expression_source_text=expression_source_text,
        expression_span=expression_span,
        anchors=anchor_requirements,
    )
    ordered_hunks = sorted(
        hunk_map,
        key=lambda hunk: _hunk_priority(hunk),
    )
    generated = _generate_candidates(
        expression_source_text,
        expression_span,
        ordered_hunks,
        max_subhunks=max_subhunks,
        max_candidates=max_candidates,
        required_anchor_count=len(anchor_requirements),
        target_function=target_function,
        source_function=patch_function,
    )
    scored = _attach_candidate_scores(
        generated,
        candidate_score_payloads=candidate_score_payloads,
        anchor_requirements=anchor_requirements,
        expression_frontier=expression_frontier,
        structural_frontier=structural_frontier,
        max_normalized_diff_lines=max_normalized_diff_lines,
    )

    scored_candidates = [
        candidate for candidate in scored
        if candidate.score_payload is not None
    ]
    best_preserving = _best_preserving(scored_candidates)
    best_structural = _best_structural(scored_candidates)
    terminal_blockers = _terminal_blockers(
        scored_candidates,
        generation_blockers=generation_blockers,
        max_normalized_diff_lines=max_normalized_diff_lines,
    )
    status = _report_status(
        generated_count=len(scored),
        scored_count=len(scored_candidates),
        best_preserving=best_preserving,
        terminal_blockers=terminal_blockers,
    )
    next_actions = _next_actions(
        status=status,
        scored_count=len(scored_candidates),
        generated_count=len(scored),
        has_manual_blockers=any(
            blocker.get("blocker") == "manual-subhunk-range-required"
            for blocker in generation_blockers
        ),
    )
    return ReconciliationReport(
        status=status,
        class_id=CLASS_ID,
        frontiers={
            "expression": expression_frontier.to_summary(),
            "structural": structural_frontier.to_summary(),
            "target_function": target_function,
            "source_function": patch_function,
            "max_normalized_diff_lines": max_normalized_diff_lines,
        },
        anchor_requirements=anchor_requirements,
        generated_count=len(scored),
        scored_count=len(scored_candidates),
        candidates=tuple(sorted(scored, key=lambda candidate: candidate.rank_key)),
        best_preserving_candidate=best_preserving,
        best_structural_candidate=best_structural,
        terminal_blockers=tuple(terminal_blockers),
        generation_blockers=tuple(generation_blockers),
        next_actions=next_actions,
    )


def build_anchor_requirements(
    expression_score: Mapping[str, Any] | None,
) -> tuple[tuple[ExpressionAnchorRequirement, ...], tuple[dict[str, Any], ...]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(expression_score, Mapping):
        return (), ({"blocker": "missing-expression-score"},)
    if _false_positive_count(expression_score) > 0:
        blockers.append({
            "blocker": "expression-frontier-virtual-id-false-positive",
            "false_positive_virtual_id_hit_count": _false_positive_count(
                expression_score
            ),
        })

    raw_virtuals = expression_score.get("virtuals")
    if not isinstance(raw_virtuals, Mapping):
        return (), (*blockers, {"blocker": "missing-expression-virtuals"})

    anchors: list[ExpressionAnchorRequirement] = []
    for raw_key, raw_entry in raw_virtuals.items():
        if not isinstance(raw_entry, Mapping):
            continue
        baseline_virtual = _int_or_none(
            raw_entry.get("baseline_virtual", raw_key)
        )
        expected = _int_or_none(raw_entry.get("expected"))
        actual = _int_or_none(raw_entry.get("actual"))
        signature = raw_entry.get("signature")
        if (
            baseline_virtual is None
            or expected is None
            or not isinstance(signature, Mapping)
        ):
            blockers.append({
                "blocker": "malformed-expression-anchor",
                "baseline_virtual": raw_key,
            })
            continue
        label = _anchor_label(raw_entry)
        anchors.append(
            ExpressionAnchorRequirement(
                baseline_virtual=baseline_virtual,
                expected=expected,
                signature=dict(signature),
                label=label,
            )
        )
        if (
            raw_entry.get("status") != "ok"
            or raw_entry.get("matched") is not True
            or actual != expected
        ):
            blockers.append({
                "blocker": "expression-frontier-anchor-not-retained",
                "baseline_virtual": baseline_virtual,
                "status": raw_entry.get("status"),
                "actual": actual,
                "expected": expected,
                "label": label,
            })
    targeted = _int_or_none(expression_score.get("targeted"))
    if targeted is not None and targeted != len(anchors):
        blockers.append({
            "blocker": "expression-frontier-target-count-mismatch",
            "targeted": targeted,
            "anchors": len(anchors),
        })
    if not anchors:
        blockers.append({"blocker": "no-expression-anchor-requirements"})
    return tuple(anchors), tuple(blockers)


def evaluate_anchor_preservation(
    candidate_score_payload: Mapping[str, Any],
    anchor_requirements: Sequence[ExpressionAnchorRequirement],
) -> tuple[dict[int, dict[str, Any]], int, tuple[str, ...]]:
    expression_score = _expression_score_from_payload(candidate_score_payload)
    preservation: dict[int, dict[str, Any]] = {}
    blockers: list[str] = []
    if not isinstance(expression_score, Mapping):
        return {}, 0, ("missing-expression-score",)
    virtuals = expression_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}, 0, ("missing-expression-virtuals",)
    if _false_positive_count(expression_score) > 0:
        blockers.append("protected-virtual-id-false-positive")

    preserved = 0
    for requirement in anchor_requirements:
        entry = _candidate_anchor_entry(virtuals, requirement)
        if entry is None:
            preservation[requirement.baseline_virtual] = {
                "status": "missing-expression",
                "matched": False,
                "expected": requirement.expected,
                "label": requirement.label,
            }
            blockers.append(
                f"missing-protected-anchor:{requirement.baseline_virtual}"
            )
            continue
        actual = _int_or_none(entry.get("actual"))
        candidate_virtual = _int_or_none(entry.get("candidate_virtual"))
        signature = entry.get("signature")
        signature_ok = (
            isinstance(signature, Mapping)
            and _signature_key(signature) == _signature_key(requirement.signature)
        )
        status = str(entry.get("status") or "")
        matched = (
            status == requirement.required_status
            and entry.get("matched") is True
            and actual == requirement.expected
            and signature_ok
        )
        if matched:
            preserved += 1
        else:
            blocker = _anchor_blocker(requirement, entry, signature_ok)
            blockers.append(blocker)
        preservation[requirement.baseline_virtual] = {
            "status": status or None,
            "matched": matched,
            "expected": requirement.expected,
            "actual": actual,
            "candidate_virtual": candidate_virtual,
            "renumbered": (
                candidate_virtual is not None
                and candidate_virtual != requirement.baseline_virtual
            ),
            "signature_match": signature_ok,
            "label": requirement.label,
        }
    return preservation, preserved, tuple(dict.fromkeys(blockers))


def score_source_hint(
    candidate_path: str,
    *,
    function: str,
    cflags_from: str | None = None,
) -> dict[str, Any]:
    command = [
        "melee-agent",
        "debug",
        "target",
        "score-source",
        candidate_path,
        "-f",
        function,
    ]
    if cflags_from:
        command.extend(["--cflags-from", cflags_from])
    command.extend([
        "--target",
        "<target.json>",
        "--expression-baseline",
        "<baseline.pcdump.txt>",
        "--expression-source",
        "<baseline-source.c>",
        "--expression-reg-class",
        "fpr",
        "--checkdiff-guard",
        "--json",
    ])
    return {
        "status": "ready",
        "path": candidate_path,
        "function": function,
        "cflags_from": cflags_from,
        "command": " ".join(shlex.quote(part) for part in command),
    }


def render_text(report: ReconciliationReport) -> str:
    lines = [
        f"status: {report.status}",
        f"class_id: {report.class_id}",
        f"generated: {report.generated_count}",
        f"scored: {report.scored_count}",
    ]
    for blocker in report.terminal_blockers:
        lines.append(
            f"blocker: {blocker.get('blocker')} - {blocker.get('reason', '')}"
        )
    if report.best_preserving_candidate is not None:
        candidate = report.best_preserving_candidate
        lines.append(
            "best_preserving: "
            f"{candidate.candidate_id} "
            f"normalized_diff_lines={candidate.normalized_diff_lines}"
        )
    if report.best_structural_candidate is not None:
        candidate = report.best_structural_candidate
        lines.append(
            "best_structural: "
            f"{candidate.candidate_id} "
            f"normalized_diff_lines={candidate.normalized_diff_lines} "
            f"anchors={candidate.preserved_anchor_count}"
        )
    for candidate in report.candidates[:10]:
        suffix = ""
        if candidate.path:
            suffix = f" -> {candidate.path}"
        lines.append(f"candidate: {candidate.candidate_id}{suffix}")
        if candidate.score_source is not None:
            lines.append(f"  score: {candidate.score_source.get('command')}")
    if report.next_actions:
        lines.append("next_actions:")
        lines.extend(f"  - {action}" for action in report.next_actions)
    return "\n".join(lines)


def with_candidate_output_metadata(
    report: ReconciliationReport,
    *,
    output_dir: Path,
    function: str,
    cflags_from: str | None,
    repo_root: Path | None = None,
) -> ReconciliationReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[ReconciliationCandidate] = []
    for candidate in report.candidates:
        path = output_dir / f"{candidate.candidate_id}.c"
        path.write_text(candidate.source_text, encoding="utf-8")
        hint_path = _display_path(path, repo_root=repo_root)
        candidates.append(
            _replace_candidate_metadata(
                candidate,
                path=str(path),
                score_source=score_source_hint(
                    hint_path,
                    function=function,
                    cflags_from=cflags_from,
                ),
            )
        )
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    best_preserving = (
        by_id.get(report.best_preserving_candidate.candidate_id)
        if report.best_preserving_candidate is not None
        else None
    )
    best_structural = (
        by_id.get(report.best_structural_candidate.candidate_id)
        if report.best_structural_candidate is not None
        else None
    )
    return ReconciliationReport(
        status=report.status,
        class_id=report.class_id,
        frontiers=report.frontiers,
        anchor_requirements=report.anchor_requirements,
        generated_count=report.generated_count,
        scored_count=report.scored_count,
        candidates=tuple(candidates),
        best_preserving_candidate=best_preserving,
        best_structural_candidate=best_structural,
        terminal_blockers=report.terminal_blockers,
        next_actions=report.next_actions,
        generation_blockers=report.generation_blockers,
    )


def _frontier(
    *,
    frontier_id: str,
    role: str,
    path: Path | None,
    source_text: str,
    target_function: str,
    source_function: str,
    score_payload: Mapping[str, Any] | None,
    anchors: tuple[ExpressionAnchorRequirement, ...],
    expression_score: Mapping[str, Any] | None = None,
) -> ReconciliationFrontierSource:
    expression_payload = (
        expression_score or _expression_score_from_payload(score_payload)
    )
    return ReconciliationFrontierSource(
        frontier_id=frontier_id,
        role=role,
        path=path,
        source_text=source_text,
        target_function=target_function,
        source_function=source_function,
        score_payload=score_payload,
        anchors=anchors,
        expression_matched=_int_or_none(
            expression_payload.get("matched")
            if isinstance(expression_payload, Mapping)
            else None
        ),
        expression_targeted=_int_or_none(
            expression_payload.get("targeted")
            if isinstance(expression_payload, Mapping)
            else None
        ),
        structural_guard=_mapping_or_none(
            score_payload.get("structural_guard")
            if isinstance(score_payload, Mapping)
            else None
        ),
        normalized_diff_lines=_extract_normalized_diff_lines(score_payload),
        frame_size=_extract_frame_size(score_payload),
    )


def _function_pair(
    expression_source_text: str,
    structural_source_text: str,
    source_function: str,
) -> tuple[FunctionSpan, str, str] | None:
    expression_span = find_function(expression_source_text, source_function)
    structural_span = find_function(structural_source_text, source_function)
    if expression_span is None or structural_span is None:
        return None
    expression_function = expression_source_text[
        expression_span.sig_start:expression_span.full_end
    ]
    structural_function = structural_source_text[
        structural_span.sig_start:structural_span.full_end
    ]
    return expression_span, expression_function, structural_function


def _manual_subhunk_overlaps_blocker(
    manual_subhunks: Sequence[SourceHunk],
    blocker: Mapping[str, Any],
) -> bool:
    base_range = blocker.get("base_range")
    if not isinstance(base_range, Mapping):
        return False
    start = _int_or_none(base_range.get("start"))
    end = _int_or_none(base_range.get("end"))
    if start is None or end is None:
        return False
    block_start = start - 1
    block_end = block_start if base_range.get("empty") is True else end
    return any(
        line_ranges_overlap(
            hunk.base_start,
            hunk.base_end,
            block_start,
            block_end,
        )
        for hunk in manual_subhunks
    )


def _reconciliation_hunks(
    hunks: Sequence[SourceHunk],
    *,
    frontier_id: str,
    expression_source_text: str,
    expression_span: FunctionSpan,
    anchors: Sequence[ExpressionAnchorRequirement],
) -> tuple[ReconciliationHunk, ...]:
    function_start_line = (
        expression_source_text[:expression_span.sig_start].count("\n") + 1
    )
    output: list[ReconciliationHunk] = []
    for hunk in hunks:
        overlaps = _anchor_line_overlaps(
            hunk,
            function_start_line=function_start_line,
            anchors=anchors,
        )
        output.append(
            ReconciliationHunk.from_source_hunk(
                hunk,
                parent_frontier_id=frontier_id,
                protected_anchor_overlap=overlaps,
                structural_intent=_structural_intents(hunk),
            )
        )
    return tuple(output)


def _generate_candidates(
    expression_source_text: str,
    expression_span: FunctionSpan,
    hunks: Sequence[ReconciliationHunk],
    *,
    max_subhunks: int,
    max_candidates: int,
    required_anchor_count: int,
    target_function: str,
    source_function: str,
) -> tuple[ReconciliationCandidate, ...]:
    expression_function = expression_source_text[
        expression_span.sig_start:expression_span.full_end
    ]
    candidates: list[ReconciliationCandidate] = []
    seen_sources: set[str] = set()
    max_width = max(1, max_subhunks)
    for width in range(1, max_width + 1):
        for combo in itertools.combinations(hunks, width):
            source_hunks = tuple(hunk.source_hunk for hunk in combo)
            if any(source_hunk is None for source_hunk in source_hunks):
                continue
            actual_hunks = tuple(
                source_hunk for source_hunk in source_hunks
                if source_hunk is not None
            )
            if hunks_overlap(actual_hunks):
                continue
            try:
                patched_function = apply_hunks_to_text(expression_function, actual_hunks)
            except ValueError:
                continue
            patched_source = (
                expression_source_text[:expression_span.sig_start]
                + patched_function
                + expression_source_text[expression_span.full_end:]
            )
            if patched_source == expression_source_text or patched_source in seen_sources:
                continue
            seen_sources.add(patched_source)
            candidate_id = _candidate_id(combo)
            manual_subhunk = any(
                "manual-protected-expression-subhunk"
                in (
                    hunk.source_hunk.blockers
                    if hunk.source_hunk is not None
                    else ()
                )
                for hunk in combo
            )
            candidates.append(
                ReconciliationCandidate(
                    candidate_id=candidate_id,
                    source_text=patched_source,
                    applied_hunks=combo,
                    provenance={
                        "target_function": target_function,
                        "source_function": source_function,
                        "required_anchor_count": required_anchor_count,
                        "hunk_ids": [hunk.hunk_id for hunk in combo],
                        "structural_intent": list(
                            dict.fromkeys(
                                intent
                                for hunk in combo
                                for intent in hunk.structural_intent
                            )
                        ),
                        "manual_subhunk": manual_subhunk,
                    },
                )
            )
            if 0 <= max_candidates <= len(candidates):
                return tuple(candidates)
    return tuple(candidates)


def _attach_candidate_scores(
    candidates: Sequence[ReconciliationCandidate],
    *,
    candidate_score_payloads: Sequence[Mapping[str, Any]],
    anchor_requirements: Sequence[ExpressionAnchorRequirement],
    expression_frontier: ReconciliationFrontierSource,
    structural_frontier: ReconciliationFrontierSource,
    max_normalized_diff_lines: int,
) -> tuple[ReconciliationCandidate, ...]:
    scores_by_id = _candidate_scores_by_id(candidate_score_payloads)
    output: list[ReconciliationCandidate] = []
    for candidate in candidates:
        score_payload = scores_by_id.get(candidate.candidate_id)
        if score_payload is None:
            output.append(candidate)
            continue
        preservation, preserved, blockers = evaluate_anchor_preservation(
            score_payload,
            anchor_requirements,
        )
        normalized = _extract_normalized_diff_lines(score_payload)
        frame_size = _extract_frame_size(score_payload)
        structural_guard = _mapping_or_none(score_payload.get("structural_guard"))
        structural_guard_accepted = bool(
            structural_guard and structural_guard.get("accepted") is True
        )
        structural_improved = (
            normalized is not None and normalized < max_normalized_diff_lines
        )
        frame_improved = _frame_improved(
            candidate_frame=frame_size,
            expression_frame=expression_frontier.frame_size,
            structural_frame=structural_frontier.frame_size,
        )
        provenance = dict(candidate.provenance)
        if frame_size is not None:
            provenance["frame_size"] = frame_size
        output.append(
            ReconciliationCandidate(
                candidate_id=candidate.candidate_id,
                source_text=candidate.source_text,
                applied_hunks=candidate.applied_hunks,
                provenance=provenance,
                score_payload=score_payload,
                anchor_preservation=preservation,
                preserved_anchor_count=preserved,
                lost_anchor_blockers=blockers,
                normalized_diff_lines=normalized,
                frame_improved=frame_improved,
                structural_improved=structural_improved,
                structural_guard_accepted=structural_guard_accepted,
                score_error=_score_error(score_payload),
                score_source=candidate.score_source,
                path=candidate.path,
            )
        )
    return tuple(output)


def _candidate_scores_by_id(
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    scores: dict[str, Mapping[str, Any]] = {}
    for payload in _flatten_candidate_payloads(payloads):
        candidate_id = _payload_candidate_id(payload)
        if candidate_id is None:
            continue
        scores[candidate_id] = payload
    return scores


def _flatten_candidate_payloads(
    payloads: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    flattened: list[Mapping[str, Any]] = []
    for payload in payloads:
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            flattened.extend(
                item for item in raw_candidates if isinstance(item, Mapping)
            )
        else:
            flattened.append(payload)
    return flattened


def _payload_candidate_id(payload: Mapping[str, Any]) -> str | None:
    for key in ("candidate_id", "id", "probe_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("path", "source_file", "score_json"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            candidate_id = _candidate_id_from_evidence_filename(value)
            if candidate_id is not None:
                return candidate_id
    return None


def _candidate_id_from_evidence_filename(path: str | Path) -> str | None:
    name = Path(path).name
    if not name:
        return None
    for suffix in _EVIDENCE_CANDIDATE_ID_SUFFIXES:
        if name.endswith(suffix):
            candidate_id = name[: -len(suffix)]
            return candidate_id or None
    return Path(name).stem or None


def _terminal_blockers(
    scored_candidates: Sequence[ReconciliationCandidate],
    *,
    generation_blockers: Sequence[Mapping[str, Any]],
    max_normalized_diff_lines: int,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for blocker in generation_blockers:
        if blocker.get("blocker") == "manual-subhunk-range-required":
            blockers.append({
                "blocker": "manual-subhunk-range-required",
                "reason": "broad hunks crossed brace/control boundaries",
                "hunk_id": blocker.get("hunk_id"),
            })
    if not scored_candidates:
        return _dedupe_blockers(blockers)

    preserving = [
        candidate for candidate in scored_candidates
        if candidate.all_anchors_preserved
    ]
    improved = [
        candidate for candidate in scored_candidates
        if candidate.structural_improved
    ]
    if preserving and not any(candidate.structural_improved for candidate in preserving):
        blockers.append({
            "blocker": "structural-ceiling-with-protected-anchors",
            "reason": (
                "at least one scored candidate preserved all anchors, but none "
                f"crossed normalized_diff_lines < {max_normalized_diff_lines}"
            ),
            "threshold": max_normalized_diff_lines,
            "best_normalized_diff_lines": min(
                (
                    candidate.normalized_diff_lines
                    for candidate in preserving
                    if candidate.normalized_diff_lines is not None
                ),
                default=None,
            ),
        })
    if improved and not any(candidate.all_anchors_preserved for candidate in improved):
        blockers.append({
            "blocker": "all-recombines-lost-protected-anchors",
            "reason": (
                "every scored recombine that improved structural drift lost at "
                "least one protected expression anchor"
            ),
        })
        manual_lost = [
            candidate for candidate in improved
            if candidate.provenance.get("manual_subhunk") is True
            and candidate.lost_anchor_blockers
        ]
        if manual_lost:
            blockers.append({
                "blocker": "protected-subhunk-lost-expression-anchor",
                "reason": (
                    "explicit protected subhunk candidates scored but still "
                    "lost protected expression anchors"
                ),
                "candidates": [
                    candidate.candidate_id for candidate in manual_lost
                ],
            })

    direct_lost = [
        candidate for candidate in scored_candidates
        if "direct-callarg" in candidate.provenance.get("structural_intent", ())
        and candidate.lost_anchor_blockers
    ]
    if direct_lost:
        blockers.append({
            "blocker": "direct-callarg-anchor-incompatibility",
            "reason": (
                "direct call-argument structural imports lost protected "
                "expression anchors"
            ),
            "candidates": [candidate.candidate_id for candidate in direct_lost],
        })
        if any(_lost_fsubs_anchor(candidate) for candidate in direct_lost):
            blockers.append({
                "blocker": "fsubs-anchor-structural-incompatibility",
                "reason": (
                    "structural imports associated with direct call-argument "
                    "shape lost fsubs-labelled protected anchors"
                ),
            })

    unsafe = [
        candidate for candidate in scored_candidates
        if candidate.score_error
        or (
            isinstance(candidate.score_payload, Mapping)
            and candidate.score_payload.get("unsafe_local_pcdump_lane") is not None
        )
    ]
    if unsafe:
        blockers.append({
            "blocker": "candidate-score-timeout-or-unsafe-lane",
            "reason": "one or more supplied candidate score payloads were unscoreable",
            "candidates": [candidate.candidate_id for candidate in unsafe],
        })
    return _dedupe_blockers(blockers)


def _report_status(
    *,
    generated_count: int,
    scored_count: int,
    best_preserving: ReconciliationCandidate | None,
    terminal_blockers: Sequence[Mapping[str, Any]],
) -> str:
    if best_preserving is not None and best_preserving.structural_guard_accepted:
        return "success"
    if scored_count:
        if terminal_blockers:
            return "blocked"
        return "scored"
    if generated_count:
        return "generated"
    return "blocked"


def _next_actions(
    *,
    status: str,
    scored_count: int,
    generated_count: int,
    has_manual_blockers: bool,
) -> tuple[str, ...]:
    actions: list[str] = []
    if generated_count and scored_count < generated_count:
        actions.append(
            "score generated probes with the emitted debug target score-source "
            "commands, then pass their JSON via --candidate-score-json"
        )
    if has_manual_blockers:
        actions.append(
            "provide manual subhunk ranges for brace/control-crossing hunks; "
            "v1 intentionally does not guess those splits"
        )
    if status == "blocked":
        actions.append(
            "treat terminal blockers as evidence for manual matching or a "
            "future scored wrapper; v1 generation is exhausted"
        )
    return tuple(actions)


def _blocked_report(
    *,
    expression_frontier: ReconciliationFrontierSource,
    structural_frontier: ReconciliationFrontierSource,
    anchors: Sequence[ExpressionAnchorRequirement],
    generation_blockers: tuple[dict[str, Any], ...],
) -> ReconciliationReport:
    return ReconciliationReport(
        status="blocked",
        class_id=CLASS_ID,
        frontiers={
            "expression": expression_frontier.to_summary(),
            "structural": structural_frontier.to_summary(),
            "target_function": expression_frontier.target_function,
            "source_function": expression_frontier.source_function,
            "max_normalized_diff_lines": DEFAULT_MAX_NORMALIZED_DIFF_LINES,
        },
        anchor_requirements=tuple(anchors),
        generated_count=0,
        scored_count=0,
        candidates=(),
        best_preserving_candidate=None,
        best_structural_candidate=None,
        terminal_blockers=tuple(generation_blockers),
        next_actions=("fix reconciliation inputs and rerun generation",),
        generation_blockers=generation_blockers,
    )


def _best_preserving(
    candidates: Sequence[ReconciliationCandidate],
) -> ReconciliationCandidate | None:
    preserving = [candidate for candidate in candidates if candidate.all_anchors_preserved]
    if not preserving:
        return None
    return sorted(preserving, key=lambda candidate: candidate.rank_key)[0]


def _best_structural(
    candidates: Sequence[ReconciliationCandidate],
) -> ReconciliationCandidate | None:
    with_scores = [
        candidate for candidate in candidates
        if candidate.normalized_diff_lines is not None
    ]
    if not with_scores:
        return None
    return sorted(
        with_scores,
        key=lambda candidate: (
            candidate.normalized_diff_lines
            if candidate.normalized_diff_lines is not None
            else 10**9,
            -candidate.preserved_anchor_count,
            len(candidate.applied_hunks),
            candidate.candidate_id,
        ),
    )[0]


def _expression_score_from_payload(
    payload: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    expression_score = payload.get("expression_score")
    if isinstance(expression_score, Mapping):
        return expression_score
    if isinstance(payload.get("virtuals"), Mapping) and "matched" in payload:
        return payload
    return None


def _candidate_anchor_entry(
    virtuals: Mapping[str, Any],
    requirement: ExpressionAnchorRequirement,
) -> Mapping[str, Any] | None:
    raw = virtuals.get(str(requirement.baseline_virtual))
    if isinstance(raw, Mapping):
        return raw
    matches: list[Mapping[str, Any]] = []
    required_key = _signature_key(requirement.signature)
    for entry in virtuals.values():
        if not isinstance(entry, Mapping):
            continue
        baseline_virtual = _int_or_none(entry.get("baseline_virtual"))
        signature = entry.get("signature")
        if (
            baseline_virtual == requirement.baseline_virtual
            and isinstance(signature, Mapping)
            and _signature_key(signature) == required_key
        ):
            matches.append(entry)
    if len(matches) == 1:
        return matches[0]
    return None


def _anchor_blocker(
    requirement: ExpressionAnchorRequirement,
    entry: Mapping[str, Any],
    signature_ok: bool,
) -> str:
    if not signature_ok:
        return f"protected-anchor-signature-mismatch:{requirement.baseline_virtual}"
    status = str(entry.get("status") or "")
    if status and status != requirement.required_status:
        return f"protected-anchor-{status}:{requirement.baseline_virtual}"
    return f"protected-anchor-regressed:{requirement.baseline_virtual}"


def _anchor_label(entry: Mapping[str, Any]) -> str | None:
    for key in ("baseline_source", "candidate_source"):
        source = entry.get(key)
        if isinstance(source, Mapping):
            name = source.get("name")
            if isinstance(name, str) and name:
                return name
    signature = entry.get("signature")
    if isinstance(signature, Mapping):
        name = signature.get("name")
        if isinstance(name, str) and name:
            return name
        expression = signature.get("expression")
        if isinstance(expression, str) and expression:
            return expression
        opcode = signature.get("opcode")
        if isinstance(opcode, str) and opcode:
            return opcode
    return None


def _signature_key(signature: Mapping[str, Any]) -> str:
    return json.dumps(signature, sort_keys=True, separators=(",", ":"))


def _false_positive_count(expression_score: Mapping[str, Any]) -> int:
    count = _int_or_none(expression_score.get("false_positive_virtual_id_hit_count"))
    if count is not None:
        return count
    hits = expression_score.get("false_positive_virtual_id_hits")
    if isinstance(hits, Sequence) and not isinstance(hits, (str, bytes)):
        return len(hits)
    return 0


def _structural_intents(hunk: SourceHunk) -> tuple[str, ...]:
    changed = "\n".join([*hunk.removed, *hunk.added])
    added = "\n".join(hunk.added)
    removed = "\n".join(hunk.removed)
    intents: list[str] = []
    if re.search(r"\w+\s*\([^;]*\(f32\)", added) and "=" in removed:
        intents.append("direct-callarg")
    if "mn_GetDigitCount" in changed:
        intents.append("digit-count-order")
    if "col_offset_product" in changed or re.search(r"\by_spacing\b.*\*", changed):
        intents.append("product-order")
    if any("f25" in line or "-176" in line for line in hunk.added + hunk.removed):
        intents.append("frame-pressure")
    if hunk.kind == "declaration":
        intents.append("declaration-only")
    if not intents:
        intents.append(hunk.kind)
    return tuple(dict.fromkeys(intents))


def _hunk_priority(hunk: ReconciliationHunk) -> tuple[int, int, int, str]:
    intents = set(hunk.structural_intent)
    if "direct-callarg" in intents:
        priority = 0
    elif "frame-pressure" in intents:
        priority = 1
    elif "product-order" in intents or "digit-count-order" in intents:
        priority = 2
    elif "declaration-only" in intents:
        priority = 4
    else:
        priority = 3
    return (priority, hunk.base_start, hunk.base_end - hunk.base_start, hunk.hunk_id)


def _candidate_id(hunks: Sequence[ReconciliationHunk]) -> str:
    raw = "-".join(hunk.hunk_id for hunk in hunks)
    if len(raw) <= 48:
        return f"reconcile-{raw}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"reconcile-{len(hunks)}h-{digest}"


def _anchor_line_overlaps(
    hunk: SourceHunk,
    *,
    function_start_line: int,
    anchors: Sequence[ExpressionAnchorRequirement],
) -> tuple[int, ...]:
    start_line = function_start_line + hunk.base_start
    end_line = function_start_line + hunk.base_end - 1
    if hunk.base_start == hunk.base_end:
        return ()
    overlaps: list[int] = []
    for anchor in anchors:
        line = _anchor_source_line(anchor)
        if line is not None and start_line <= line <= end_line:
            overlaps.append(anchor.baseline_virtual)
    return tuple(overlaps)


def _anchor_source_line(anchor: ExpressionAnchorRequirement) -> int | None:
    for key in ("source_line", "line"):
        value = anchor.signature.get(key)
        line = _int_or_none(value)
        if line is not None:
            return line
    return None


def _extract_normalized_diff_lines(payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    direct = _int_or_none(payload.get("normalized_diff_lines"))
    if direct is not None:
        return direct
    structural_guard = payload.get("structural_guard")
    if isinstance(structural_guard, Mapping):
        direct = _int_or_none(structural_guard.get("normalized_diff_lines"))
        if direct is not None:
            return direct
        truth_gate = structural_guard.get("structural_truth_gate")
        if isinstance(truth_gate, Mapping):
            direct = _int_or_none(truth_gate.get("normalized_diff_lines"))
            if direct is not None:
                return direct
    checkdiff = payload.get("checkdiff")
    if isinstance(checkdiff, Mapping):
        return _extract_normalized_diff_lines(checkdiff)
    return None


def _extract_frame_size(payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("frame_size", "current_frame_size", "frame_size_actual"):
        value = _int_or_none(payload.get(key))
        if value is not None:
            return value
    target_score = payload.get("target_score")
    if isinstance(target_score, Mapping):
        frame = target_score.get("frame")
        if isinstance(frame, Mapping):
            value = _int_or_none(frame.get("size_actual"))
            if value is not None:
                return value
    structural_guard = payload.get("structural_guard")
    if isinstance(structural_guard, Mapping):
        for key in ("current_frame_size", "frame_size"):
            value = _int_or_none(structural_guard.get(key))
            if value is not None:
                return value
        stack = structural_guard.get("stack_frame_sizes")
        if isinstance(stack, Mapping):
            value = _int_or_none(stack.get("current_frame_size"))
            if value is not None:
                return value
    return None


def _frame_improved(
    *,
    candidate_frame: int | None,
    expression_frame: int | None,
    structural_frame: int | None,
) -> bool:
    if candidate_frame is None or expression_frame is None:
        return False
    if structural_frame is not None:
        return abs(candidate_frame - structural_frame) < abs(
            expression_frame - structural_frame
        )
    return candidate_frame < expression_frame


def _score_error(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("error") or payload.get("structural_guard_error")
    return str(value) if value is not None else None


def _lost_fsubs_anchor(candidate: ReconciliationCandidate) -> bool:
    for key, entry in candidate.anchor_preservation.items():
        if entry.get("matched") is True:
            continue
        label = str(entry.get("label") or "").lower()
        if "fsubs" in label or key in {33, 35}:
            return True
    return False


def _replace_candidate_metadata(
    candidate: ReconciliationCandidate,
    *,
    path: str | None = None,
    score_source: Mapping[str, Any] | None = None,
) -> ReconciliationCandidate:
    return ReconciliationCandidate(
        candidate_id=candidate.candidate_id,
        source_text=candidate.source_text,
        applied_hunks=candidate.applied_hunks,
        provenance=candidate.provenance,
        score_payload=candidate.score_payload,
        anchor_preservation=candidate.anchor_preservation,
        preserved_anchor_count=candidate.preserved_anchor_count,
        lost_anchor_blockers=candidate.lost_anchor_blockers,
        normalized_diff_lines=candidate.normalized_diff_lines,
        frame_improved=candidate.frame_improved,
        structural_improved=candidate.structural_improved,
        structural_guard_accepted=candidate.structural_guard_accepted,
        score_error=candidate.score_error,
        score_source=score_source,
        path=path,
    )


def _display_path(path: Path, *, repo_root: Path | None) -> str:
    if repo_root is not None:
        try:
            return str(path.resolve().relative_to(repo_root.resolve())).replace(
                "\\",
                "/",
            )
        except (OSError, ValueError):
            pass
    return str(path)


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _one_based_range(start: int, end: int) -> dict[str, Any]:
    empty = start == end
    return {
        "start": start + 1,
        "end": end if not empty else start,
        "empty": empty,
    }


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    output: list[dict[str, Any]] = []
    for blocker in blockers:
        key = (blocker.get("blocker"), blocker.get("hunk_id"))
        if key in seen:
            continue
        seen.add(key)
        output.append(dict(blocker))
    return output
