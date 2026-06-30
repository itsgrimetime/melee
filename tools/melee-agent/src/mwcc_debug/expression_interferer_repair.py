"""Expression-aware FPR interferer repair evaluation helpers.

This module is intentionally pure: it consumes score/residual payloads produced
by existing mwcc-debug commands and ranks them without compiling, shelling out,
or mutating source. A CLI can wrap these helpers later, but the policy and
summary logic stay unit-testable here.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MISSING = object()
_POST_BRIDGE_EXHAUSTION_KIND = (
    "no-expression-progress-after-row-fsubs-and-support-orders"
)
_POST_BRIDGE_EXHAUSTED_ROUTES = (
    "row_fsubs_owner_repair",
    "non_satisfied_select_order",
)
_POST_BRIDGE_CONCRETE_SUPPORT_ORDER_FAMILIES = (
    "retained_fpr_case_c_target_live_range_repair",
    "protected_expression_row_product_generation",
    "product_operand_ownership",
    "row_offset_first_scaled_ownership",
    "product_sink_ownership",
    "row_offset_sink_branch_ownership",
    "digit_guarded_statement_motion",
)
_POST_BRIDGE_SUPPRESSED_FAMILIES = (
    "row_fsubs_owner_repair",
    "protected_expression_row_product_generation",
    "row_offset_first_scaled_ownership",
    "product_sink_ownership",
    "product_operand_ownership",
    "row_offset_sink_branch_ownership",
    "digit_guarded_statement_motion",
    "paired_row_product_recombine",
)


@dataclass(frozen=True)
class ProtectedExpressionPolicy:
    """Focus/protected anchor policy for expression-score payloads.

    The v1 default matches the issue-876 lane: the focus is named by source
    expression identity, and every other expression anchor is protected.
    """

    focus_name: str
    focus_baseline_virtual: int | None = None
    protected_baseline_virtuals: frozenset[int] | None = None


@dataclass(frozen=True)
class ExpressionRepairCandidate:
    candidate_id: str
    target_score: Mapping[str, Any] | None = None
    expression_score: Mapping[str, Any] | None = None
    structural_guard: Mapping[str, Any] | None = None
    residual: Mapping[str, Any] | None = None
    source_hunks: tuple[Any, ...] = ()
    provenance: str | None = None
    match_percent: float | None = None
    source_line_delta: int = 0
    exploratory: bool = False
    structural_guard_error: str | None = None
    error: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExpressionRepairCandidate:
        hunks = payload.get("source_hunks", payload.get("hunks", ()))
        if hunks is None:
            hunks = ()
        elif isinstance(hunks, (str, bytes)):
            hunks = (hunks,)
        else:
            hunks = tuple(hunks)

        known = {
            "candidate_id",
            "id",
            "probe_id",
            "target_score",
            "expression_score",
            "structural_guard",
            "residual",
            "source_hunks",
            "hunks",
            "provenance",
            "match_percent",
            "source_line_delta",
            "exploratory",
            "structural_guard_error",
            "error",
        }
        extra = {k: v for k, v in payload.items() if k not in known}
        return cls(
            candidate_id=str(
                payload.get("candidate_id")
                or payload.get("id")
                or payload.get("probe_id")
                or "candidate"
            ),
            target_score=_mapping_or_none(payload.get("target_score")),
            expression_score=_mapping_or_none(payload.get("expression_score")),
            structural_guard=_mapping_or_none(payload.get("structural_guard")),
            residual=_mapping_or_none(payload.get("residual")),
            source_hunks=hunks,
            provenance=_str_or_none(payload.get("provenance")),
            match_percent=_float_or_none(payload.get("match_percent")),
            source_line_delta=_int_or_default(payload.get("source_line_delta"), 0),
            exploratory=bool(payload.get("exploratory", False)),
            structural_guard_error=_str_or_none(payload.get("structural_guard_error")),
            error=_str_or_none(payload.get("error")),
            extra=extra,
        )


@dataclass(frozen=True)
class CandidateAssessment:
    candidate: ExpressionRepairCandidate
    accepted: bool
    recommendation: str
    blockers: tuple[str, ...]
    focus_matched: bool
    focus_actual: int | None
    focus_expected: int | None
    focus_candidate_virtual: int | None
    focus_baseline_virtual: int | None
    protected_matched: int
    protected_targeted: int
    expression_matched: int
    expression_targeted: int
    expression_virtual_distance: int
    structural_guard_accepted: bool
    residual: dict[str, Any] | None

    @property
    def primary_success(self) -> bool:
        return (
            self.accepted
            and self.focus_matched
            and self.protected_matched == self.protected_targeted
        )

    @property
    def rank_key(self) -> tuple[Any, ...]:
        residual_rank = _residual_rank(self.residual, self)
        match_percent = (
            self.candidate.match_percent
            if self.candidate.match_percent is not None
            else -1.0
        )
        return (
            -int(self.primary_success),
            -self.protected_matched,
            self.expression_virtual_distance,
            -residual_rank,
            -int(self.structural_guard_accepted),
            len(self.candidate.source_hunks),
            abs(self.candidate.source_line_delta),
            -float(match_percent),
            self.candidate.candidate_id,
        )

    def to_summary(self) -> dict[str, Any]:
        residual_case = _case_value(self.residual)
        summary: dict[str, Any] = {
            "candidate_id": self.candidate.candidate_id,
            "accepted": self.accepted,
            "recommendation": self.recommendation,
            "blockers": list(self.blockers),
            "focus": {
                "baseline_virtual": self.focus_baseline_virtual,
                "candidate_virtual": self.focus_candidate_virtual,
                "actual": self.focus_actual,
                "expected": self.focus_expected,
                "matched": self.focus_matched,
            },
            "protected_matched": self.protected_matched,
            "protected_targeted": self.protected_targeted,
            "expression_matched": self.expression_matched,
            "expression_targeted": self.expression_targeted,
            "expression_virtual_distance": self.expression_virtual_distance,
            "structural_guard_accepted": self.structural_guard_accepted,
        }
        if residual_case is not None:
            summary["residual_case"] = residual_case
        if self.residual and self.residual.get("blocker_source") is not None:
            summary["blocker_source"] = self.residual["blocker_source"]
        if self.candidate.source_hunks:
            summary["source_hunks"] = list(self.candidate.source_hunks)
        if isinstance(self.candidate.expression_score, Mapping):
            expression_summary: dict[str, Any] = {
                "matched": self.expression_matched,
                "targeted": self.expression_targeted,
                "virtual_distance": self.expression_virtual_distance,
            }
            virtuals = self.candidate.expression_score.get("virtuals")
            if virtuals is not None:
                expression_summary["virtuals"] = virtuals
            summary["expression_score"] = expression_summary
        if self.candidate.target_score is not None:
            summary["target_score"] = dict(self.candidate.target_score)
        if self.candidate.match_percent is not None:
            summary["match_percent"] = self.candidate.match_percent
        if self.candidate.structural_guard is not None:
            summary["structural_guard"] = dict(self.candidate.structural_guard)
        if self.candidate.structural_guard_error is not None:
            summary["structural_guard_error"] = self.candidate.structural_guard_error
        for key in (
            "path",
            "score_source",
            "source_file",
            "checkdiff",
            "checkdiff_drift",
            "diagnostics_path",
            "score_source_path",
        ):
            if key in self.candidate.extra:
                summary[key] = self.candidate.extra[key]
        return summary


@dataclass(frozen=True)
class SourceGenerationCandidate:
    candidate_id: str
    family: str
    strategy: str
    priority: int
    rationale: str
    expected_effect: str
    source_text: str
    source_hunks: tuple[dict[str, Any], ...]
    blocker_cases: tuple[str, ...] = ()
    validation_hint: str | None = None
    validation_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "family": self.family,
            "strategy": self.strategy,
            "priority": self.priority,
            "rationale": self.rationale,
            "expected_effect": self.expected_effect,
            "source_hunks": list(self.source_hunks),
            "blocker_cases": list(self.blocker_cases),
        }
        if self.validation_hint is not None:
            data["validation_hint"] = self.validation_hint
        if self.validation_metadata:
            data["validation_metadata"] = dict(self.validation_metadata)
        if include_source:
            data["source_text"] = self.source_text
        return data


@dataclass(frozen=True)
class _StatementSpan:
    start: int
    end: int
    text: str
    indent: str
    lhs: str | None = None


@dataclass(frozen=True)
class _RowProductSourceModel:
    function_span: Any
    function_text: str
    row_unscaled_local: str
    row_scaled_local: str
    row_cast_expr: str
    row_first_def: _StatementSpan
    row_scaled_def: _StatementSpan
    row_adj_def: _StatementSpan | None
    digit_count_call: _StatementSpan | None
    product_local: str
    product_def: _StatementSpan
    product_handoff: _StatementSpan | None
    col_sink_uses: tuple[_StatementSpan, ...]
    row_sink_uses: tuple[_StatementSpan, ...]
    row_adj_sink_uses: tuple[_StatementSpan, ...]


def evaluate_candidate(
    candidate: ExpressionRepairCandidate,
    policy: ProtectedExpressionPolicy,
) -> CandidateAssessment:
    """Apply expression-protection gates and classify a candidate."""

    blockers: list[str] = []
    expression_score = candidate.expression_score
    if not isinstance(expression_score, Mapping):
        blockers.append("missing-expression-score")
        expression_score = {}

    virtuals = _virtuals(expression_score)
    focus_key, focus = _focus_entry(virtuals, policy)
    protected = _protected_entries(virtuals, policy, focus_key)

    if candidate.error:
        blockers.append("candidate-did-not-compile")

    focus_matched = bool(focus and focus.get("matched") is True)
    focus_actual = _int_or_none(focus.get("actual") if focus else None)
    focus_expected = _int_or_none(focus.get("expected") if focus else None)
    focus_candidate_virtual = _int_or_none(
        focus.get("candidate_virtual") if focus else None
    )
    focus_baseline_virtual = _int_or_none(
        focus.get("baseline_virtual", focus_key) if focus else focus_key
    )
    if focus is None:
        blockers.append("missing-focus-expression")

    protected_targeted = len(protected)
    protected_matched = 0
    protected_regressed = False
    protected_false_hit = False
    protected_bad_status = False
    false_hit_baselines = _false_positive_baselines(expression_score)
    for baseline_virtual, entry in protected:
        if entry.get("status") != "ok":
            protected_bad_status = True
        if entry.get("matched") is True and entry.get("status") == "ok":
            protected_matched += 1
        else:
            protected_regressed = True
        if (
            entry.get("virtual_id_false_positive")
            or baseline_virtual in false_hit_baselines
        ):
            protected_false_hit = True

    if protected_regressed or protected_bad_status:
        blockers.append("protected-expression-regressed")
    if protected_false_hit:
        blockers.append("protected-virtual-id-false-positive")

    structural_guard_accepted = _structural_guard_accepted(candidate.structural_guard)
    if not structural_guard_accepted:
        blockers.append("structural-guard-rejected")

    expression_targeted = _int_or_default(
        expression_score.get("targeted"),
        len(virtuals),
    )
    expression_matched = _int_or_default(
        expression_score.get("matched"),
        sum(1 for item in virtuals.values() if item.get("matched") is True),
    )
    expression_virtual_distance = _int_or_default(
        expression_score.get("virtual_distance"),
        max(0, expression_targeted - expression_matched),
    )

    residual = (
        dict(candidate.residual)
        if isinstance(candidate.residual, Mapping)
        else None
    )
    accepted = not blockers
    if candidate.exploratory and not accepted:
        recommendation = "exploratory-only"
    elif accepted and focus_matched and protected_matched == protected_targeted:
        recommendation = "recommend"
    elif accepted:
        recommendation = "ranked-partial"
    else:
        recommendation = "reject"

    return CandidateAssessment(
        candidate=candidate,
        accepted=accepted,
        recommendation=recommendation,
        blockers=tuple(dict.fromkeys(blockers)),
        focus_matched=focus_matched,
        focus_actual=focus_actual,
        focus_expected=focus_expected,
        focus_candidate_virtual=focus_candidate_virtual,
        focus_baseline_virtual=focus_baseline_virtual,
        protected_matched=protected_matched,
        protected_targeted=protected_targeted,
        expression_matched=expression_matched,
        expression_targeted=expression_targeted,
        expression_virtual_distance=expression_virtual_distance,
        structural_guard_accepted=structural_guard_accepted,
        residual=residual,
    )


def derive_focus_force_map(
    expression_score: Mapping[str, Any],
    policy: ProtectedExpressionPolicy,
) -> dict[int, int]:
    """Build a force map keyed by the focus anchor's candidate virtual.

    Expression scoring follows source identity across renumbering, so residual
    analysis must force the candidate virtual, not the baseline virtual id.
    """

    virtuals = _virtuals(expression_score)
    focus_key, focus = _focus_entry(virtuals, policy)
    if focus is None:
        return {}
    candidate_virtual = _int_or_none(focus.get("candidate_virtual"))
    if candidate_virtual is None:
        candidate_virtual = _int_or_none(focus.get("baseline_virtual", focus_key))
    expected = _int_or_none(focus.get("expected"))
    if candidate_virtual is None or expected is None:
        return {}
    return {candidate_virtual: expected}


def attach_residual_labels(
    residual: Mapping[str, Any],
    *,
    expression_score: Mapping[str, Any],
    policy: ProtectedExpressionPolicy,
    blocker_attribution: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Attach expression-first focus/blocker labels to a residual fact."""

    labeled = dict(residual)
    virtuals = _virtuals(expression_score)
    focus_key, focus = _focus_entry(virtuals, policy)

    if focus is not None:
        labeled["focus_label"] = _anchor_label(focus) or policy.focus_name
        labeled["focus_baseline_virtual"] = _int_or_none(
            focus.get("baseline_virtual", focus_key)
        )
        labeled["focus_candidate_virtual"] = _int_or_none(
            focus.get("candidate_virtual")
        )
        labeled["focus_actual"] = _int_or_none(focus.get("actual"))
        labeled["focus_expected"] = _int_or_none(focus.get("expected"))
    else:
        labeled["focus_label"] = policy.focus_name

    source = residual.get("source")
    if isinstance(source, Mapping):
        advisory_name = source.get("var_name") or source.get("name")
        if advisory_name is not None:
            labeled["advisory_focus_name"] = str(advisory_name)
            labeled["advisory_focus_confidence"] = _str_or_none(
                source.get("confidence")
            )
            labeled["advisory_focus_role"] = "low-confidence-diagnostic"

    blocker_ig = _int_or_none(residual.get("blocker_ig"))
    blocker_source = _blocker_source_from_attribution(
        blocker_attribution,
        blocker_ig,
    )
    if blocker_source is not None:
        labeled["blocker_source"] = blocker_source["name"]
        if blocker_source.get("confidence") is not None:
            labeled["blocker_source_confidence"] = blocker_source["confidence"]
        if blocker_source.get("expression") is not None:
            labeled["blocker_expression"] = blocker_source["expression"]
        if blocker_source.get("first_def") is not None:
            labeled["blocker_first_def"] = blocker_source["first_def"]
    elif residual.get("blocker_source") is not None:
        labeled["blocker_source"] = str(residual["blocker_source"])

    return labeled


def rank_candidates(
    candidates: Sequence[ExpressionRepairCandidate],
    policy: ProtectedExpressionPolicy,
) -> list[CandidateAssessment]:
    assessments = [evaluate_candidate(candidate, policy) for candidate in candidates]
    return sorted(assessments, key=lambda assessment: assessment.rank_key)


def build_terminal_summary(
    candidates: Sequence[ExpressionRepairCandidate],
    policy: ProtectedExpressionPolicy,
    *,
    attempted_families: Sequence[str] = (),
    recombine_status: str = "not-run",
) -> dict[str, Any]:
    """Summarize bounded exhaustion when no expression-legal 6/6 candidate wins."""

    ranked = rank_candidates(candidates, policy)
    winner = next((item for item in ranked if item.primary_success), None)
    if winner is not None:
        return {
            "status": "success",
            "kind": "expression-scored-fpr-case-a-c2-success",
            "winner": winner.to_summary(),
            "ranked_candidates": [item.to_summary() for item in ranked],
        }

    best = ranked[0] if ranked else None
    focus_name = policy.focus_name
    focus_expected = best.focus_expected if best else None
    best_actual = best.focus_actual if best else None

    remaining_blockers = _remaining_blockers(ranked, focus_name)
    summary: dict[str, Any] = {
        "status": "blocked",
        "kind": "expression-scored-fpr-case-a-c2-exhaustion",
        "focus": {
            "name": focus_name,
            "expected": focus_expected,
            "best_actual": best_actual,
        },
        "protected": {
            "required": _protected_required(best),
            "best_preserved": best.protected_matched if best else 0,
        },
        "remaining_blockers": remaining_blockers,
        "attempted_families": list(attempted_families),
        "recombine_status": recombine_status,
        "ranked_candidates": [item.to_summary() for item in ranked],
    }
    if best is not None:
        summary["best_candidate"] = best.to_summary()
    post_bridge_exhaustion = _post_bridge_expression_exhaustion(
        ranked,
        attempted_families,
        remaining_blockers,
    )
    if post_bridge_exhaustion is not None:
        summary["post_bridge_terminal_summary"] = post_bridge_exhaustion
        _mark_sticky_pool_bridge_routes_exhausted(
            remaining_blockers,
            exhausted_routes=post_bridge_exhaustion["exhausted_routes"],
        )
    return summary


def _attempted_route_set(summary_or_families: Any) -> set[str]:
    if isinstance(summary_or_families, Mapping):
        raw = summary_or_families.get("attempted_families", ())
    else:
        raw = summary_or_families
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raw = (raw,) if raw else ()

    normalized: set[str] = set()
    for item in raw:
        if item is None:
            continue
        route = str(item).strip().lower().replace("-", "_")
        if route:
            normalized.add(route)
    return normalized


def _attempted_routes_for_post_bridge(attempted_families: Sequence[str]) -> set[str]:
    routes = _attempted_route_set(attempted_families)
    if set(_POST_BRIDGE_CONCRETE_SUPPORT_ORDER_FAMILIES) <= routes:
        routes.add("non_satisfied_select_order")
    return routes


def _post_bridge_expression_exhaustion(
    ranked: Sequence[CandidateAssessment],
    attempted_families: Sequence[str],
    remaining_blockers: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    attempted_routes = _attempted_routes_for_post_bridge(attempted_families)
    if not set(_POST_BRIDGE_EXHAUSTED_ROUTES) <= attempted_routes:
        return None
    if any(item.primary_success for item in ranked):
        return None
    if any(_assessment_has_expression_progress(item) for item in ranked):
        return None

    c2_blocker = _ready_sticky_pool_c2_blocker(remaining_blockers)
    if c2_blocker is None:
        return None

    best = ranked[0] if ranked else None
    best_by_expression = (
        sorted(
            ranked,
            key=lambda item: (
                -item.expression_matched,
                item.expression_virtual_distance,
                item.candidate.candidate_id,
            ),
        )[0]
        if ranked
        else None
    )
    return {
        "status": "blocked",
        "kind": _POST_BRIDGE_EXHAUSTION_KIND,
        "terminal_blocker": "current-source-shape-allocator-ceiling",
        "exhausted_routes": list(_POST_BRIDGE_EXHAUSTED_ROUTES),
        "attempted_families": list(attempted_families),
        "attempted_families_normalized": sorted(attempted_routes),
        "best_candidate": best.to_summary() if best is not None else None,
        "evidence": {
            "candidate_count": len(ranked),
            "best_expression_matched": (
                best_by_expression.expression_matched
                if best_by_expression is not None
                else 0
            ),
            "best_expression_targeted": (
                best_by_expression.expression_targeted
                if best_by_expression is not None
                else 0
            ),
            "best_expression_virtual_distance": (
                best_by_expression.expression_virtual_distance
                if best_by_expression is not None
                else 0
            ),
            "focus": c2_blocker.get("focus"),
            "focus_ig": c2_blocker.get("focus_ig"),
            "paired_source": c2_blocker.get("paired_source"),
            "paired_ig": c2_blocker.get("paired_ig"),
            "current_focus_reg": c2_blocker.get("current_focus_reg"),
            "current_paired_reg": c2_blocker.get("current_paired_reg"),
            "target_reg": c2_blocker.get("target_reg"),
            "paired_target_reg": c2_blocker.get("paired_target_reg"),
        },
    }


def _assessment_has_expression_progress(assessment: CandidateAssessment) -> bool:
    return (
        assessment.expression_matched > 0
        or assessment.focus_matched
        or assessment.protected_matched > 0
    )


def _ready_sticky_pool_c2_blocker(
    remaining_blockers: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for blocker in remaining_blockers:
        if not isinstance(blocker, Mapping):
            continue
        if _case_value(blocker) != "C2":
            continue
        bridge = blocker.get("sticky_pool_bridge")
        if not isinstance(bridge, Mapping):
            continue
        if bridge.get("status") == "ready":
            return blocker
    return None


def _mark_sticky_pool_bridge_routes_exhausted(
    remaining_blockers: Sequence[Mapping[str, Any]],
    *,
    exhausted_routes: Sequence[str],
) -> None:
    for blocker in remaining_blockers:
        if not isinstance(blocker, dict):
            continue
        bridge = blocker.get("sticky_pool_bridge")
        if not isinstance(bridge, dict) or bridge.get("status") != "ready":
            continue
        bridge["route_status"] = "exhausted"
        bridge["exhausted_routes"] = list(exhausted_routes)
        bridge["next_action"] = "terminal-summary"
        row_repair = bridge.get("row_fsubs_owner_repair")
        if isinstance(row_repair, dict):
            row_repair["route_status"] = "exhausted"


def _post_bridge_terminal_exhaustion(
    terminal_summary: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(terminal_summary, Mapping):
        return None
    terminal = terminal_summary.get("post_bridge_terminal_summary")
    if isinstance(terminal, Mapping) and terminal.get("kind") == (
        _POST_BRIDGE_EXHAUSTION_KIND
    ):
        return terminal
    if terminal_summary.get("kind") == _POST_BRIDGE_EXHAUSTION_KIND:
        return terminal_summary
    return None


def _blocked_post_bridge_source_generation(
    *,
    function: str,
    terminal_summary: Mapping[str, Any] | None,
    terminal_exhaustion: Mapping[str, Any],
) -> dict[str, Any]:
    exhausted_routes = list(
        terminal_exhaustion.get("exhausted_routes")
        or _POST_BRIDGE_EXHAUSTED_ROUTES
    )
    return {
        "status": "blocked",
        "kind": "expression-aware-source-generation",
        "function": function,
        "families": [],
        "blocker_cases": _source_generation_blocker_cases(terminal_summary),
        "terminal_summary_kind": (
            terminal_summary.get("kind")
            if isinstance(terminal_summary, Mapping)
            else None
        ),
        "terminal_blocker": terminal_exhaustion.get(
            "terminal_blocker",
            "current-source-shape-allocator-ceiling",
        ),
        "reason": (
            "row-fsubs owner repair and non-satisfied select-order routes "
            "were already expression-scored without progress"
        ),
        "exhausted_routes": exhausted_routes,
        "suppressed_families": list(_POST_BRIDGE_SUPPRESSED_FAMILIES),
        "candidate_ids": [],
        "candidates": [],
    }


def _source_generation_family_key(family: str) -> str:
    return family.strip().lower().replace("-", "_")


def _filter_attempted_source_generation_candidates(
    candidates: Sequence[SourceGenerationCandidate],
    terminal_summary: Mapping[str, Any] | None,
) -> tuple[list[SourceGenerationCandidate], list[SourceGenerationCandidate]]:
    attempted = _attempted_route_set(terminal_summary)
    if not attempted:
        return list(candidates), []

    kept: list[SourceGenerationCandidate] = []
    suppressed: list[SourceGenerationCandidate] = []
    for candidate in candidates:
        if _source_generation_family_key(candidate.family) in attempted:
            suppressed.append(candidate)
        else:
            kept.append(candidate)
    return kept, suppressed


def _limited_source_generation_candidates(
    candidates: Sequence[SourceGenerationCandidate],
    max_candidates: int,
) -> list[SourceGenerationCandidate]:
    if max_candidates < 0:
        return list(candidates)
    return list(candidates[:max_candidates])


def _blocked_attempted_source_generation(
    *,
    function: str,
    terminal_summary: Mapping[str, Any] | None,
    suppressed_candidates: Sequence[SourceGenerationCandidate],
) -> dict[str, Any]:
    suppressed_families = list(
        dict.fromkeys(candidate.family for candidate in suppressed_candidates)
    )
    return {
        "status": "blocked",
        "kind": "expression-aware-source-generation",
        "function": function,
        "families": [],
        "blocker_cases": _source_generation_blocker_cases(terminal_summary),
        "terminal_summary_kind": (
            terminal_summary.get("kind")
            if isinstance(terminal_summary, Mapping)
            else None
        ),
        "terminal_blocker": "current-source-shape-allocator-ceiling",
        "reason": (
            "attempted source-generation families were already "
            "expression-scored without progress"
        ),
        "suppressed_families": suppressed_families,
        "candidate_ids": [
            candidate.candidate_id for candidate in suppressed_candidates
        ],
        "candidates": [],
    }


def expression_problem_source_reachable(
    natural: ExpressionRepairCandidate,
    force: ExpressionRepairCandidate,
    policy: ProtectedExpressionPolicy,
) -> dict[str, Any]:
    """Compare natural and forced expression scores for the issue-876 proof."""

    natural_assessment = evaluate_candidate(natural, policy)
    force_assessment = evaluate_candidate(force, policy)
    expected = force_assessment.focus_expected or natural_assessment.focus_expected
    return {
        "source_reachable": bool(
            expected is not None
            and natural_assessment.focus_actual != expected
            and force_assessment.focus_actual == expected
            and force_assessment.protected_matched
            == force_assessment.protected_targeted
        ),
        "natural_focus_actual": natural_assessment.focus_actual,
        "force_focus_actual": force_assessment.focus_actual,
        "focus_expected": expected,
        "protected_preserved": natural_assessment.protected_matched,
    }


def generate_source_repair_candidates(
    source_text: str,
    *,
    function: str,
    terminal_summary: Mapping[str, Any] | None = None,
    max_candidates: int = 16,
    include_source: bool = False,
) -> dict[str, Any]:
    """Generate bounded source candidates for protected FPR Case A/C2 repair.

    The generator intentionally emits source-actionable candidates and hunks
    only. Existing compile/score commands remain responsible for validation.
    """

    if _find_function_span(source_text, function) is None:
        return {
            "status": "blocked",
            "kind": "expression-aware-source-generation",
            "reason": f"target function {function} not found in source",
            "candidates": [],
        }

    terminal_exhaustion = _post_bridge_terminal_exhaustion(terminal_summary)
    if terminal_exhaustion is not None:
        return _blocked_post_bridge_source_generation(
            function=function,
            terminal_summary=terminal_summary,
            terminal_exhaustion=terminal_exhaustion,
        )

    blockers = _source_generation_blocker_cases(terminal_summary)
    all_candidates = _source_generation_candidates_with_text(
        source_text,
        function=function,
        terminal_summary=terminal_summary,
        max_candidates=-1,
    )
    candidates, suppressed_candidates = (
        _filter_attempted_source_generation_candidates(
            all_candidates,
            terminal_summary,
        )
    )
    if all_candidates and suppressed_candidates and not candidates:
        return _blocked_attempted_source_generation(
            function=function,
            terminal_summary=terminal_summary,
            suppressed_candidates=suppressed_candidates,
        )

    candidates = _limited_source_generation_candidates(candidates, max_candidates)
    emitted_families = list(dict.fromkeys(candidate.family for candidate in candidates))
    return {
        "status": "generated" if candidates else "blocked",
        "kind": "expression-aware-source-generation",
        "function": function,
        "families": emitted_families or ["protected_expression_row_product_generation"],
        "blocker_cases": blockers,
        "candidates": [
            candidate.to_dict(include_source=include_source)
            for candidate in candidates
        ],
        "terminal_summary_kind": (
            terminal_summary.get("kind")
            if isinstance(terminal_summary, Mapping)
            else None
        ),
        **(
            {
                "suppressed_families": list(
                    dict.fromkeys(
                        candidate.family for candidate in suppressed_candidates
                    )
                ),
                "suppressed_candidate_ids": [
                    candidate.candidate_id for candidate in suppressed_candidates
                ],
            }
            if suppressed_candidates
            else {}
        ),
        "stop_condition": (
            "validate generated candidates with expression_score; if none "
            "reaches 6/6, keep terminal summary naming row_offset/product and "
            "C2 sticky-pool blockers"
        ),
        **(
            {
                "reason": "no supported row_offset/product source anchors found",
                "missing_patterns": _source_generation_missing_patterns(
                    source_text,
                    function,
                ),
            }
            if not candidates
            else {}
        ),
    }


def generate_source_repair_candidate_files(
    source_text: str,
    *,
    function: str,
    terminal_summary: Mapping[str, Any] | None,
    output_dir: Any,
    max_candidates: int = 16,
) -> dict[str, Any]:
    generation = generate_source_repair_candidates(
        source_text,
        function=function,
        terminal_summary=terminal_summary,
        max_candidates=max_candidates,
    )
    out_dir = output_dir if isinstance(output_dir, Path) else Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if generation.get("status") == "blocked" and not generation.get("candidates"):
        generation["output_dir"] = str(out_dir)
        return generation

    candidates = _source_generation_candidates_with_text(
        source_text,
        function=function,
        terminal_summary=terminal_summary,
        max_candidates=max_candidates,
    )
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for row in generation.get("candidates", []):
        if not isinstance(row, dict):
            continue
        candidate = by_id.get(str(row.get("candidate_id")))
        if candidate is None:
            continue
        path = out_dir / f"{candidate.candidate_id}.c"
        path.write_text(candidate.source_text)
        row["path"] = str(path)
    generation["output_dir"] = str(out_dir)
    return generation


def _source_generation_candidates_with_text(
    source_text: str,
    *,
    function: str,
    terminal_summary: Mapping[str, Any] | None,
    max_candidates: int,
) -> list[SourceGenerationCandidate]:
    function_span = _find_function_span(source_text, function)
    if function_span is None:
        return []

    blockers = _source_generation_blocker_cases(terminal_summary)
    validation_hint = _source_generation_validation_hint(function)
    model = _extract_row_product_source_model(source_text, function_span)
    candidates: list[SourceGenerationCandidate] = []
    seen: set[str] = set()

    def add_candidate(
        *,
        candidate_id: str,
        family: str,
        strategy: str,
        priority: int,
        rationale: str,
        expected_effect: str,
        patched: str | None,
        blocker_cases: tuple[str, ...],
        validation_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if patched is None or patched == source_text or patched in seen:
            return
        patched_span = _find_function_span(patched, function)
        if patched_span is not None and _has_duplicate_f32_declarations(
            patched[patched_span.sig_start:patched_span.full_end]
        ):
            return
        seen.add(patched)
        candidates.append(
            SourceGenerationCandidate(
                candidate_id=candidate_id,
                family=family,
                strategy=strategy,
                priority=priority,
                rationale=rationale,
                expected_effect=expected_effect,
                source_text=patched,
                source_hunks=tuple(
                    _source_hunks(source_text, patched, candidate_id=candidate_id)
                ),
                blocker_cases=blocker_cases,
                validation_hint=validation_hint,
                validation_metadata=dict(validation_metadata or {}),
            )
        )

    add_candidate(
        candidate_id="row-offset-owner-split",
        family="protected_expression_row_product_generation",
        strategy="row-offset-owner-split",
        priority=100,
        rationale=(
            "Split the row_offset blocker value from its later scaled use so "
            "the product and row-offset lifetimes can be colored independently."
        ),
        expected_effect=(
            "shorten the live range holding the unscaled row_offset blocker "
            "while preserving the protected product expression anchors"
        ),
        patched=_patch_row_offset_owner_split(source_text, function_span),
        blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
    )
    add_candidate(
        candidate_id="product-owner-sticky-copy",
        family="protected_expression_row_product_generation",
        strategy="product-owner-sticky-copy",
        priority=95,
        rationale=(
            "Materialize an owner copy for col_offset_product_fpr before it "
            "feeds col_offset, giving the sticky FPR pool a source-visible "
            "copy to compensate Case C2."
        ),
        expected_effect=(
            "preserve protected anchors while testing whether a product owner "
            "copy can move the focus product out of f25/f30"
        ),
        patched=_patch_product_owner_copy(source_text, function_span),
        blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
    )
    add_candidate(
        candidate_id="row-owner-product-interleave",
        family="protected_expression_row_product_generation",
        strategy="row-owner-product-interleave",
        priority=90,
        rationale=(
            "Interleave the source-visible product assignment between the "
            "unscaled row_offset owner and scaled row_offset use."
        ),
        expected_effect=(
            "test the row_offset/product live-range boundary directly while "
            "keeping the protected col/load anchors source-identical"
        ),
        patched=_patch_row_owner_product_interleave(source_text, function_span),
        blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
    )

    if model is not None:
        row_fsubs_validation = _source_generation_row_fsubs_validation_metadata(
            terminal_summary
        )
        add_candidate(
            candidate_id="row-fsubs-call-result-owner",
            family="row_fsubs_owner_repair",
            strategy="row-fsubs-call-result-owner",
            priority=89,
            rationale=(
                "Materialize the HSD_JObjGetTranslationY call result before "
                "the row fsubs owner so expression scoring can validate the "
                "row first-def ownership separately from source motion."
            ),
            expected_effect=(
                "test whether the row fsubs first-def owner can move toward "
                "f26 without accepting structural similarity alone"
            ),
            patched=_patch_row_fsubs_call_result_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"C2"}),
            validation_metadata=row_fsubs_validation,
        )
        add_candidate(
            candidate_id="row-fsubs-owner-temp",
            family="row_fsubs_owner_repair",
            strategy="row-fsubs-owner-temp",
            priority=88,
            rationale=(
                "Materialize the complete row fsubs expression into a "
                "source-visible owner temp before assigning row_offset."
            ),
            expected_effect=(
                "test whether a distinct row fsubs owner is needed for the "
                "row/col C2 swap while requiring expression-score movement"
            ),
            patched=_patch_row_fsubs_owner_temp(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"C2"}),
            validation_metadata=row_fsubs_validation,
        )
        add_candidate(
            candidate_id="row-first-def-owner-copy",
            family="row_offset_first_scaled_ownership",
            strategy="row-first-def-owner-copy",
            priority=85,
            rationale=(
                "Copy the unscaled row value immediately after its first "
                "definition and use that owner for the scaled row product."
            ),
            expected_effect=(
                "test whether the blocker should die at the row first-def "
                "while preserving a separate scaled row local"
            ),
            patched=_patch_row_first_def_owner_copy(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="row-scaled-def-owner-copy",
            family="row_offset_first_scaled_ownership",
            strategy="row-scaled-def-owner-copy",
            priority=84,
            rationale=(
                "Materialize a source-visible owner for the scaled row value "
                "before assigning it back to row_offset."
            ),
            expected_effect=(
                "give MWCC a distinct owner for the scaled row value without "
                "extending the unscaled row blocker"
            ),
            patched=_patch_row_scaled_def_owner_copy(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="product-local-materialize",
            family="product_sink_ownership",
            strategy="product-local-materialize",
            priority=83,
            rationale=(
                "Restore an explicit col_offset_product_fpr materialization "
                "when retained source only has a direct col_offset product."
            ),
            expected_effect=(
                "make the focus product source identity explicit in probes "
                "that lost the product local"
            ),
            patched=_patch_product_local_materialize(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="product-col-cast-owner-materialize",
            family="product_operand_ownership",
            strategy="product-col-cast-owner-materialize",
            priority=88,
            rationale=(
                "Materialize the casted col operand feeding "
                "col_offset = y_spacing * (f32) col so the product operand "
                "has its own source-visible FPR owner."
            ),
            expected_effect=(
                "test whether the cast operand owner, rather than the final "
                "col_offset product, controls the sticky-pool admission point"
            ),
            patched=_patch_product_col_cast_operand_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"C2"}),
        )
        add_candidate(
            candidate_id="product-y-spacing-owner-materialize",
            family="product_operand_ownership",
            strategy="product-y-spacing-owner-materialize",
            priority=87,
            rationale=(
                "Materialize the y_spacing operand feeding the col_offset "
                "product so the non-cast product input can be colored as a "
                "separate FPR owner."
            ),
            expected_effect=(
                "test whether the y_spacing product operand should own the "
                "FPR pressure that currently appears as a row/col C2 swap"
            ),
            patched=_patch_product_y_spacing_operand_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"C2"}),
        )
        add_candidate(
            candidate_id="product-combined-operand-owners",
            family="product_operand_ownership",
            strategy="product-combined-operand-owners",
            priority=86,
            rationale=(
                "Materialize both source operands of the col_offset product "
                "before multiplying them."
            ),
            expected_effect=(
                "test the combined operand-owner pressure shape without "
                "moving row_offset or relying on a pair-only row/col order"
            ),
            patched=_patch_product_combined_operand_owners(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"C2"}),
        )
        add_candidate(
            candidate_id="product-col-offset-sink-owner",
            family="product_sink_ownership",
            strategy="product-col-offset-sink-owner",
            priority=82,
            rationale=(
                "Copy col_offset into a sink-side FPR owner immediately before "
                "the first X translate/source sink."
            ),
            expected_effect=(
                "test whether the product should stay isolated until the "
                "actual col_offset sink"
            ),
            patched=_patch_product_col_offset_sink_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="row-translate-sink-owner",
            family="row_offset_sink_branch_ownership",
            strategy="row-translate-sink-owner",
            priority=81,
            rationale=(
                "Copy row_offset into a sink-side owner immediately before "
                "the row translate/source sink."
            ),
            expected_effect=(
                "shorten the row_offset value competing with the product for "
                "the target FPR"
            ),
            patched=_patch_row_translate_sink_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="row-adj-translate-sink-owner",
            family="row_offset_sink_branch_ownership",
            strategy="row-adj-translate-sink-owner",
            priority=80,
            rationale=(
                "Copy row_offset_adj into a sink-side owner immediately before "
                "the adjusted row translate/source sink."
            ),
            expected_effect=(
                "isolate the adjusted row value from the first row offset "
                "value"
            ),
            patched=_patch_row_adj_translate_sink_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="row-branch-sink-owner-pair",
            family="row_offset_sink_branch_ownership",
            strategy="row-branch-sink-owner-pair",
            priority=79,
            rationale=(
                "Apply row_offset and row_offset_adj sink owners together "
                "when both branch sinks are present."
            ),
            expected_effect=(
                "test whether both branch sinks, rather than the producer, "
                "need ownership to remove the interference"
            ),
            patched=_patch_row_branch_sink_owner_pair(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="product-handoff-late-owner",
            family="product_sink_ownership",
            strategy="product-handoff-late-owner",
            priority=78,
            rationale=(
                "Move the product-to-col_offset handoff through a late owner "
                "immediately before the first col_offset sink."
            ),
            expected_effect=(
                "separate product computation from final col_offset liveness"
            ),
            patched=_patch_product_handoff_late_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="digit-guard-product-before-count",
            family="digit_guarded_statement_motion",
            strategy="digit-guard-product-before-count",
            priority=77,
            rationale=(
                "Move only the pure product assignment and handoff before "
                "mn_GetDigitCount."
            ),
            expected_effect=(
                "test product lifetime relative to the digit-count call while "
                "keeping row scaling after the call"
            ),
            patched=_patch_digit_guard_product_before_count(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="digit-guard-row-scale-before-count",
            family="digit_guarded_statement_motion",
            strategy="digit-guard-row-scale-before-count",
            priority=76,
            rationale=(
                "Move the pure rowf/row scale/row adjusted assignments before "
                "mn_GetDigitCount."
            ),
            expected_effect=(
                "test whether row_offset should be fixed before the call "
                "while the product keeps the current protected order"
            ),
            patched=_patch_digit_guard_row_scale_before_count(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="digit-guard-product-after-row-scale",
            family="digit_guarded_statement_motion",
            strategy="digit-guard-product-after-row-scale",
            priority=75,
            rationale=(
                "Move the pure product assignment and handoff after the row "
                "scale/adjusted assignments."
            ),
            expected_effect=(
                "test the inverse guarded order without moving protected "
                "calls, loop setup, or branch code"
            ),
            patched=_patch_digit_guard_product_after_row_scale(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="row-scaled-adj-direct-owner",
            family="row_offset_first_scaled_ownership",
            strategy="row-scaled-adj-direct-owner",
            priority=74,
            rationale=(
                "Keep row_offset scaled normally but compute row_offset_adj "
                "from the direct unscaled row expression."
            ),
            expected_effect=(
                "check whether duplicating the scaled expression shifts "
                "row_offset ownership"
            ),
            patched=_patch_row_scaled_adj_direct_owner(source_text, function_span),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="paired-row-scaled-owner__product-sink-owner",
            family="paired_row_product_recombine",
            strategy="paired-row-scaled-owner__product-sink-owner",
            priority=72,
            rationale=(
                "Combine the row scaled owner copy with the product sink owner "
                "when their source hunks do not overlap."
            ),
            expected_effect=(
                "test complementary row/product ownership moves as one source "
                "probe"
            ),
            patched=_patch_paired_recombine(
                source_text,
                function_span,
                (
                    _patch_product_col_offset_sink_owner,
                    _patch_row_scaled_def_owner_copy,
                ),
            ),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="paired-row-branch-sink__product-handoff-late",
            family="paired_row_product_recombine",
            strategy="paired-row-branch-sink__product-handoff-late",
            priority=71,
            rationale=(
                "Combine paired row branch sink ownership with a late product "
                "handoff when their hunks are independent."
            ),
            expected_effect=(
                "test branch sink and product handoff ownership together"
            ),
            patched=_patch_paired_recombine(
                source_text,
                function_span,
                (
                    _patch_row_branch_sink_owner_pair,
                    _patch_product_handoff_late_owner,
                ),
            ),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )
        add_candidate(
            candidate_id="paired-row-first-owner__digit-product-before-count",
            family="paired_row_product_recombine",
            strategy="paired-row-first-owner__digit-product-before-count",
            priority=70,
            rationale=(
                "Combine row first-def ownership with guarded product motion "
                "when their source hunks are independent."
            ),
            expected_effect=(
                "test the row blocker death point and product call-side "
                "lifetime together"
            ),
            patched=_patch_paired_recombine(
                source_text,
                function_span,
                (
                    _patch_digit_guard_product_before_count,
                    _patch_row_first_def_owner_copy,
                ),
            ),
            blocker_cases=tuple(case for case in blockers if case in {"A", "C2"}),
        )

    candidates = sorted(
        candidates,
        key=lambda item: (-item.priority, item.candidate_id),
    )
    if max_candidates >= 0:
        candidates = candidates[:max_candidates]
    return candidates


def _find_function_span(source_text: str, function: str) -> Any | None:
    from .source_patch import find_function

    return find_function(source_text, function)


def _source_generation_blocker_cases(
    terminal_summary: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(terminal_summary, Mapping):
        return []
    cases: list[str] = []
    blockers = terminal_summary.get("remaining_blockers", ())
    if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
        return []
    for blocker in blockers:
        if not isinstance(blocker, Mapping):
            continue
        case = _case_value(blocker)
        if case is not None:
            cases.append(case)
    return list(dict.fromkeys(cases))


def _source_generation_row_fsubs_validation_metadata(
    terminal_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "requires_expression_score_validation": True,
        "known_negative_control": "row_sub_assign_split",
    }
    if not isinstance(terminal_summary, Mapping):
        return metadata
    blockers = terminal_summary.get("remaining_blockers", ())
    if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
        return metadata
    for blocker in blockers:
        if not isinstance(blocker, Mapping):
            continue
        bridge = blocker.get("sticky_pool_bridge")
        if not isinstance(bridge, Mapping):
            continue
        row_repair = bridge.get("row_fsubs_owner_repair")
        if not isinstance(row_repair, Mapping):
            continue
        target_ig = _int_or_none(row_repair.get("target_ig"))
        expected = _int_or_none(row_repair.get("expected_phys"))
        if target_ig is not None:
            metadata["target_expression_virtual"] = target_ig
        if expected is not None:
            metadata["expected_phys"] = expected
        break
    return metadata


def _source_generation_validation_hint(function: str) -> str:
    return (
        "Validate each emitted source path with the same expression-score "
        f"workflow used for {function}; accept only candidates that preserve "
        "protected anchors and move the focus product to its expected FPR."
    )


def _source_generation_missing_patterns(
    source_text: str,
    function: str,
) -> list[str]:
    function_span = _find_function_span(source_text, function)
    if function_span is None:
        return [f"function {function}"]
    function_text = source_text[function_span.sig_start:function_span.full_end]
    checks: tuple[tuple[str, str], ...] = (
        (
            "row first-def HSD_JObjGetTranslationY minus base",
            r"(?m)(?:^\s*(?:row_offset|y_offset)\s*=\s*"
            r"HSD_JObjGetTranslationY\(\s*jobj2\s*\)\s*-\s*base\s*;\s*$|"
            r"^\s*(?:row_offset|y_offset)\s*=\s*"
            r"HSD_JObjGetTranslationY\(\s*jobj2\s*\)\s*;\s*\n"
            r"\s*(?:row_offset|y_offset)\s*-=\s*base\s*;\s*$)",
        ),
        (
            "row scaled product assignment",
            r"(?m)(?:^\s*row_offset\s*\*=\s*[^;]+;\s*$|"
            r"^\s*row_offset\s*=\s*(?:row_offset|y_offset)\s*\*\s*[^;]+;\s*$)",
        ),
        (
            "col_offset_product_fpr product assignment",
            r"(?m)^\s*(?:col_offset_product_fpr|col_offset)\s*=\s*"
            r"y_spacing\s*\*\s*[^;]+;\s*$",
        ),
        (
            "digit_count mn_GetDigitCount anchor",
            r"(?m)^\s*digit_count\s*=\s*mn_GetDigitCount\(\s*.+?\s*\)\s*;\s*$",
        ),
    )
    missing = [label for label, pattern in checks if re.search(pattern, function_text) is None]
    return missing


def _source_hunks(
    base_source: str,
    candidate_source: str,
    *,
    candidate_id: str,
) -> list[dict[str, Any]]:
    base_lines = base_source.splitlines()
    candidate_lines = candidate_source.splitlines()
    matcher = difflib.SequenceMatcher(
        None,
        base_lines,
        candidate_lines,
        autojunk=False,
    )
    hunks: list[dict[str, Any]] = []
    for tag, base_start, base_end, cand_start, cand_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append({
            "candidate_id": candidate_id,
            "kind": tag,
            "base_start": base_start + 1,
            "base_end": base_end,
            "candidate_start": cand_start + 1,
            "candidate_end": cand_end,
            "removed": base_lines[base_start:base_end],
            "added": candidate_lines[cand_start:cand_end],
        })
    return hunks


def _replace_function_text(
    source_text: str,
    function_span: Any,
    patched_function: str,
) -> str:
    return (
        source_text[:function_span.sig_start]
        + patched_function
        + source_text[function_span.full_end:]
    )


def _insert_decl_after(
    function_text: str,
    *,
    anchor_name: str,
    declaration: str,
) -> str | None:
    if re.search(rf"\b{re.escape(declaration.split()[-1].rstrip(';'))}\b", function_text):
        return function_text
    lines = function_text.splitlines(keepends=True)
    anchor_re = re.compile(rf"^(\s*)f32\s+{re.escape(anchor_name)}\s*;\s*(?://.*)?$")
    for index, line in enumerate(lines):
        match = anchor_re.match(line.rstrip("\n"))
        if match is None:
            continue
        newline = "\n" if line.endswith("\n") else ""
        lines.insert(index + 1, f"{match.group(1)}{declaration}{newline}")
        return "".join(lines)
    return None


def _extract_row_product_source_model(
    source_text: str,
    function_span: Any,
) -> _RowProductSourceModel | None:
    function_text = source_text[function_span.sig_start:function_span.full_end]
    row_first_def = _find_statement_span(
        function_text,
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>row_offset|y_offset)\s*=\s*"
        r"HSD_JObjGetTranslationY\(\s*jobj2\s*\)\s*-\s*base\s*;\s*$",
        label="row first-def",
    )
    if row_first_def is None:
        row_first_def = _find_statement_span(
            function_text,
            r"(?m)^(?P<indent>[ \t]*)(?P<lhs>row_offset|y_offset)\s*=\s*"
            r"HSD_JObjGetTranslationY\(\s*jobj2\s*\)\s*;\s*\n"
            r"(?P=indent)(?P=lhs)\s*-=\s*base\s*;\s*$",
            label="split row first-def",
        )
    if row_first_def is None or row_first_def.lhs is None:
        return None

    row_scaled_def, row_scaled_local, row_unscaled_local, row_cast_expr = (
        _find_row_scaled_statement(function_text, row_first_def.lhs)
    )
    if row_scaled_def is None:
        return None

    row_adj_def = _find_statement_span(
        function_text,
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>row_offset_adj)\s*=\s*.+?;\s*$",
        label="row adjusted def",
    )
    digit_count_call = _find_statement_span(
        function_text,
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>digit_count)\s*=\s*"
        r"mn_GetDigitCount\(\s*.+?\s*\)\s*;\s*$",
        label="digit count",
    )
    product_def = _find_statement_span(
        function_text,
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>col_offset_product_fpr|col_offset)"
        r"\s*=\s*y_spacing\s*\*\s*[^;]+;\s*$",
        label="product def",
    )
    if product_def is None or product_def.lhs is None:
        return None

    product_handoff = None
    if product_def.lhs != "col_offset":
        product_handoff = _find_statement_span(
            function_text,
            rf"(?m)^(?P<indent>[ \t]*)(?P<lhs>col_offset)\s*=\s*"
            rf"{re.escape(product_def.lhs)}\s*;\s*$",
            label="product handoff",
        )

    return _RowProductSourceModel(
        function_span=function_span,
        function_text=function_text,
        row_unscaled_local=row_unscaled_local,
        row_scaled_local=row_scaled_local,
        row_cast_expr=row_cast_expr,
        row_first_def=row_first_def,
        row_scaled_def=row_scaled_def,
        row_adj_def=row_adj_def,
        digit_count_call=digit_count_call,
        product_local=product_def.lhs,
        product_def=product_def,
        product_handoff=product_handoff,
        col_sink_uses=tuple(_find_sink_spans(function_text, "col_offset", axis="x")),
        row_sink_uses=tuple(
            _find_sink_spans(function_text, row_scaled_local, axis="y")
        ),
        row_adj_sink_uses=tuple(
            _find_sink_spans(function_text, "row_offset_adj", axis="y")
        ),
    )


def _find_row_scaled_statement(
    function_text: str,
    row_first_local: str,
) -> tuple[_StatementSpan | None, str, str, str]:
    multiply_match = re.search(
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>row_offset)\s*\*=\s*"
        r"(?P<cast>[^;]+?)\s*;\s*$",
        function_text,
    )
    if multiply_match is not None:
        return (
            _statement_span_from_match(function_text, multiply_match),
            multiply_match.group("lhs"),
            multiply_match.group("lhs"),
            multiply_match.group("cast").strip(),
        )

    assign_match = re.search(
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>row_offset)\s*=\s*"
        r"(?P<base>row_offset|y_offset)\s*\*\s*(?P<cast>[^;]+?)\s*;\s*$",
        function_text,
    )
    if assign_match is not None:
        return (
            _statement_span_from_match(function_text, assign_match),
            assign_match.group("lhs"),
            assign_match.group("base"),
            assign_match.group("cast").strip(),
        )

    return None, "row_offset", row_first_local, "rowf"


def _find_statement_span(
    function_text: str,
    pattern: str,
    *,
    label: str,
) -> _StatementSpan | None:
    del label
    match = re.search(pattern, function_text)
    if match is None:
        return None
    return _statement_span_from_match(function_text, match)


def _statement_span_from_match(
    function_text: str,
    match: re.Match[str],
) -> _StatementSpan:
    groupdict = match.groupdict()
    text = match.group(0)
    indent = groupdict.get("indent")
    if indent is None:
        indent_match = re.match(r"[ \t]*", text)
        indent = indent_match.group(0) if indent_match else ""
    lhs = groupdict.get("lhs")
    return _StatementSpan(
        start=match.start(),
        end=match.end(),
        text=function_text[match.start():match.end()],
        indent=indent,
        lhs=lhs,
    )


def _insert_decl_after_any(
    function_text: str,
    anchor_names: Sequence[str],
    declaration: str,
) -> str | None:
    decl_match = re.match(r"\s*f32\s+([A-Za-z_]\w*)\s*;", declaration)
    if decl_match is None:
        return None
    decl_name = decl_match.group(1)
    if re.search(rf"(?m)^\s*f32\s+{re.escape(decl_name)}\s*;", function_text):
        return function_text
    for anchor_name in anchor_names:
        patched = _insert_decl_after(
            function_text,
            anchor_name=anchor_name,
            declaration=declaration,
        )
        if patched is not None:
            return patched
    return None


def _replace_statement(
    function_text: str,
    span: _StatementSpan,
    replacement: str,
) -> str:
    return function_text[:span.start] + replacement + function_text[span.end:]


def _replace_many_statements(
    function_text: str,
    replacements: Sequence[tuple[_StatementSpan, str]],
) -> str:
    patched = function_text
    for span, replacement in sorted(
        replacements,
        key=lambda item: item[0].start,
        reverse=True,
    ):
        patched = _replace_statement(patched, span, replacement)
    return patched


def _move_statement_block(
    function_text: str,
    spans: Sequence[_StatementSpan],
    *,
    before: _StatementSpan | None = None,
    after: _StatementSpan | None = None,
) -> str | None:
    if (before is None) == (after is None) or not spans:
        return None
    unique = sorted(
        {(span.start, span.end): span for span in spans}.values(),
        key=lambda span: span.start,
    )
    line_ranges = [_statement_line_range(function_text, span) for span in unique]
    for index, (start, end) in enumerate(line_ranges):
        if start >= end:
            return None
        if index and start < line_ranges[index - 1][1]:
            return None
    anchor = before if before is not None else after
    assert anchor is not None
    anchor_range = _statement_line_range(function_text, anchor)
    if any(start <= anchor_range[0] < end for start, end in line_ranges):
        return None

    lines = function_text.splitlines(keepends=True)
    block_lines: list[str] = []
    for start, end in line_ranges:
        block_lines.extend(lines[start:end])

    for start, end in reversed(line_ranges):
        del lines[start:end]

    removed_before_anchor = sum(
        end - start
        for start, end in line_ranges
        if end <= anchor_range[0]
    )
    if before is not None:
        insert_at = anchor_range[0] - removed_before_anchor
    else:
        insert_at = anchor_range[1] - removed_before_anchor
    lines[insert_at:insert_at] = block_lines
    return "".join(lines)


def _apply_model_patch(
    source_text: str,
    model: _RowProductSourceModel,
    patched_function_text: str,
) -> str:
    function_name = getattr(model.function_span, "name", None)
    source_span = (
        _find_function_span(source_text, function_name)
        if function_name
        else None
    )
    return _replace_function_text(
        source_text,
        source_span or model.function_span,
        patched_function_text,
    )


def _model_after_function_patch(
    source_text: str,
    function_span: Any,
    patched_function_text: str,
) -> _RowProductSourceModel | None:
    function_name = getattr(function_span, "name", None)
    if not function_name:
        return None
    patched_source = _replace_function_text(
        source_text,
        function_span,
        patched_function_text,
    )
    patched_span = _find_function_span(patched_source, function_name)
    if patched_span is None:
        return None
    return _extract_row_product_source_model(patched_source, patched_span)


def _source_hunk_ranges(source_hunks: Sequence[Mapping[str, Any]]) -> tuple[range, ...]:
    ranges: list[range] = []
    for hunk in source_hunks:
        start = _int_or_none(hunk.get("base_start"))
        end = _int_or_none(hunk.get("base_end"))
        if start is None or end is None:
            continue
        if end < start:
            end = start
        ranges.append(range(start, end + 1))
    return tuple(ranges)


def _hunks_non_overlapping(
    a: Sequence[Mapping[str, Any]],
    b: Sequence[Mapping[str, Any]],
) -> bool:
    a_ranges = _source_hunk_ranges(a)
    b_ranges = _source_hunk_ranges(b)
    for left in a_ranges:
        for right in b_ranges:
            if left.start < right.stop and right.start < left.stop:
                return False
    return True


def _apply_patchers_in_order(
    source_text: str,
    function_span: Any,
    patchers: Sequence[Any],
) -> str | None:
    current = source_text
    function_name = getattr(function_span, "name", None)
    if not function_name:
        return None
    for patcher in patchers:
        current_span = _find_function_span(current, function_name)
        if current_span is None:
            return None
        next_source = patcher(current, current_span)
        if next_source is None or next_source == current:
            return None
        current = next_source
    return current


def _find_rowf_assignment(function_text: str) -> _StatementSpan | None:
    return _find_statement_span(
        function_text,
        r"(?m)^(?P<indent>[ \t]*)(?P<lhs>rowf)\s*=\s*\(f32\)\s*row\s*;\s*$",
        label="rowf assignment",
    )


def _find_sink_spans(
    function_text: str,
    local: str,
    *,
    axis: str,
) -> list[_StatementSpan]:
    lines = function_text.splitlines(keepends=True)
    offset = 0
    spans: list[_StatementSpan] = []
    local_re = re.compile(rf"\b{re.escape(local)}\b")
    assignment_re = re.compile(r"^\s*[A-Za-z_]\w*\s*(?:=|\*=|-=|\+=)")
    declaration_re = re.compile(r"^\s*f32\s+")
    current_start: int | None = None
    current_lines: list[str] = []

    def maybe_add_statement(start: int, text: str) -> None:
        stripped = text.strip()
        if not stripped or not stripped.endswith(";"):
            return
        if local_re.search(text) is None:
            return
        if declaration_re.match(text) or assignment_re.match(text):
            return
        if axis == "x":
            is_sink = "HSD_JObjSetTranslateX" in text or "sink(" in text
        else:
            is_sink = "HSD_JObjSetTranslateY" in text or "sink(" in text
        if not is_sink:
            return
        indent_match = re.match(r"[ \t]*", text)
        spans.append(
            _StatementSpan(
                start=start,
                end=start + len(text),
                text=text,
                indent=indent_match.group(0) if indent_match else "",
            )
        )

    def starts_sink_statement(text: str) -> bool:
        stripped = text.strip()
        if axis == "x":
            sink_name = "HSD_JObjSetTranslateX"
        else:
            sink_name = "HSD_JObjSetTranslateY"
        return sink_name in stripped or "sink(" in stripped

    for line in lines:
        text = line.rstrip("\n")
        stripped = text.strip()
        start = offset
        end = offset + len(text)
        offset += len(line)
        if current_start is not None:
            current_lines.append(line)
            if stripped.endswith(";"):
                maybe_add_statement(
                    current_start,
                    "".join(current_lines).rstrip("\n"),
                )
                current_start = None
                current_lines = []
            continue
        if not stripped or not stripped.endswith(";"):
            if stripped and starts_sink_statement(text):
                current_start = start
                current_lines = [line]
            continue
        maybe_add_statement(start, function_text[start:end])
    return spans


def _statement_line_range(
    function_text: str,
    span: _StatementSpan,
) -> tuple[int, int]:
    start_line = function_text.count("\n", 0, span.start)
    end_line = function_text.count("\n", 0, max(span.end - 1, span.start)) + 1
    return start_line, end_line


def _product_expr(model: _RowProductSourceModel) -> str | None:
    match = re.search(r"=\s*y_spacing\s*\*\s*(?P<expr>.+?)\s*;", model.product_def.text)
    if match is None:
        return None
    return match.group("expr").strip()


def _replace_local_once(text: str, local: str, replacement: str) -> str:
    return re.sub(
        rf"\b{re.escape(local)}\b",
        replacement,
        text,
        count=1,
    )


def _sink_owner_replacement(
    span: _StatementSpan,
    *,
    local: str,
    owner: str,
) -> str:
    replaced = _replace_local_once(span.text, local, owner)
    control_match = re.match(
        r"^([ \t]*)((?:if|else if|while|for)\s*\(.*\))\s*(.+;\s*)$",
        span.text,
    )
    if control_match is not None:
        indent, control, body = control_match.groups()
        inner = indent + "    "
        return (
            f"{indent}{control} {{\n"
            f"{inner}{owner} = {local};\n"
            f"{inner}{_replace_local_once(body.strip(), local, owner)}\n"
            f"{indent}}}"
        )
    else_match = re.match(r"^([ \t]*)else\s+(.+;\s*)$", span.text)
    if else_match is not None:
        indent, body = else_match.groups()
        inner = indent + "    "
        return (
            f"{indent}else {{\n"
            f"{inner}{owner} = {local};\n"
            f"{inner}{_replace_local_once(body.strip(), local, owner)}\n"
            f"{indent}}}"
        )
    return f"{span.indent}{owner} = {local};\n{replaced}"


def _has_duplicate_f32_declarations(function_text: str) -> bool:
    names = re.findall(r"(?m)^\s*f32\s+([A-Za-z_]\w*)\s*;", function_text)
    return len(names) != len(set(names))


def _row_first_def_rhs(span: _StatementSpan) -> str | None:
    match = re.search(r"=\s*(?P<rhs>.+?)\s*;\s*$", span.text, flags=re.DOTALL)
    if match is None:
        return None
    return " ".join(match.group("rhs").split())


def _patch_row_first_def_owner_copy(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        (model.row_unscaled_local, model.row_scaled_local, "row_offset"),
        "f32 row_offset_first_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None:
        return None
    replacement_first = (
        f"{model.row_first_def.text}\n"
        f"{model.row_first_def.indent}row_offset_first_owner_fpr = "
        f"{model.row_unscaled_local};"
    )
    replacement_scaled = (
        f"{model.row_scaled_def.indent}{model.row_scaled_local} = "
        f"row_offset_first_owner_fpr * {model.row_cast_expr};"
    )
    patched = _replace_many_statements(
        model.function_text,
        (
            (model.row_first_def, replacement_first),
            (model.row_scaled_def, replacement_scaled),
        ),
    )
    return _apply_model_patch(source_text, model, patched)


def _patch_row_fsubs_call_result_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None:
        return None
    parsed = _row_fsubs_call_minus_local(_row_first_def_rhs(model.row_first_def))
    if parsed is None:
        return None
    call_expr, base_local = parsed
    patched = _insert_decl_after_any(
        model.function_text,
        (model.row_unscaled_local, model.row_scaled_local, "row_offset"),
        "f32 row_offset_call_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None:
        return None
    replacement = (
        f"{model.row_first_def.indent}row_offset_call_owner_fpr = {call_expr};\n"
        f"{model.row_first_def.indent}{model.row_unscaled_local} = "
        f"row_offset_call_owner_fpr - {base_local};"
    )
    patched = _replace_statement(model.function_text, model.row_first_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_row_fsubs_owner_temp(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None:
        return None
    rhs = _row_first_def_rhs(model.row_first_def)
    if _row_fsubs_call_minus_local(rhs) is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        (model.row_unscaled_local, model.row_scaled_local, "row_offset"),
        "f32 row_offset_fsubs_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None:
        return None
    replacement = (
        f"{model.row_first_def.indent}row_offset_fsubs_owner_fpr = {rhs};\n"
        f"{model.row_first_def.indent}{model.row_unscaled_local} = "
        "row_offset_fsubs_owner_fpr;"
    )
    patched = _replace_statement(model.function_text, model.row_first_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_row_scaled_def_owner_copy(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        (model.row_scaled_local, model.row_unscaled_local, "row_offset"),
        "f32 row_offset_scaled_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None:
        return None
    replacements: list[tuple[_StatementSpan, str]] = [
        (
            model.row_scaled_def,
            (
                f"{model.row_scaled_def.indent}row_offset_scaled_owner_fpr = "
                f"{model.row_unscaled_local} * {model.row_cast_expr};\n"
                f"{model.row_scaled_def.indent}{model.row_scaled_local} = "
                "row_offset_scaled_owner_fpr;"
            ),
        )
    ]
    if (
        model.row_adj_def is not None
        and re.search(
            rf"=\s*\(?\s*{re.escape(model.row_scaled_local)}\s*\)?\s*-\s*0\.4f\s*;",
            model.row_adj_def.text,
        )
    ):
        replacements.append(
            (
                model.row_adj_def,
                (
                    f"{model.row_adj_def.indent}row_offset_adj = "
                    "row_offset_scaled_owner_fpr - 0.4f;"
                ),
            )
        )
    patched = _replace_many_statements(model.function_text, replacements)
    return _apply_model_patch(source_text, model, patched)


def _patch_row_scaled_adj_direct_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or model.row_adj_def is None:
        return None
    if (
        model.row_unscaled_local == model.row_scaled_local
        and model.row_scaled_def.start < model.row_adj_def.start
    ):
        gap = model.function_text[model.row_scaled_def.end:model.row_adj_def.start]
        if gap.strip():
            return None
        if not re.search(
            rf"=\s*\(?\s*{re.escape(model.row_scaled_local)}\s*\)?\s*"
            r"-\s*0\.4f\s*;",
            model.row_adj_def.text,
        ):
            return None
        replacement_direct = (
            f"{model.row_scaled_def.indent}row_offset_adj = "
            f"{model.row_unscaled_local} * {model.row_cast_expr} - 0.4f;"
        )
        patched = _replace_many_statements(
            model.function_text,
            (
                (model.row_scaled_def, replacement_direct),
                (model.row_adj_def, model.row_scaled_def.text),
            ),
        )
        return _apply_model_patch(source_text, model, patched)
    replacement = (
        f"{model.row_adj_def.indent}row_offset_adj = "
        f"{model.row_unscaled_local} * {model.row_cast_expr} - 0.4f;"
    )
    patched = _replace_statement(model.function_text, model.row_adj_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_row_translate_sink_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or not model.row_sink_uses:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        (model.row_scaled_local, "row_offset"),
        "f32 row_offset_sink_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not model.row_sink_uses:
        return None
    sink = model.row_sink_uses[0]
    replacement = _sink_owner_replacement(
        sink,
        local=model.row_scaled_local,
        owner="row_offset_sink_fpr",
    )
    patched = _replace_statement(model.function_text, sink, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_row_adj_translate_sink_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or not model.row_adj_sink_uses:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        ("row_offset_adj", model.row_scaled_local, "row_offset"),
        "f32 row_offset_adj_sink_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not model.row_adj_sink_uses:
        return None
    sink = model.row_adj_sink_uses[0]
    replacement = _sink_owner_replacement(
        sink,
        local="row_offset_adj",
        owner="row_offset_adj_sink_fpr",
    )
    patched = _replace_statement(model.function_text, sink, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_row_branch_sink_owner_pair(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or not model.row_sink_uses or not model.row_adj_sink_uses:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        (model.row_scaled_local, "row_offset"),
        "f32 row_offset_sink_fpr;",
    )
    if patched is None:
        return None
    patched = _insert_decl_after_any(
        patched,
        ("row_offset_adj", model.row_scaled_local, "row_offset"),
        "f32 row_offset_adj_sink_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not model.row_sink_uses or not model.row_adj_sink_uses:
        return None
    row_sink = model.row_sink_uses[0]
    row_adj_sink = model.row_adj_sink_uses[0]
    if row_sink.start == row_adj_sink.start:
        return None
    patched = _replace_many_statements(
        model.function_text,
        (
            (
                row_sink,
                _sink_owner_replacement(
                    row_sink,
                    local=model.row_scaled_local,
                    owner="row_offset_sink_fpr",
                ),
            ),
            (
                row_adj_sink,
                _sink_owner_replacement(
                    row_adj_sink,
                    local="row_offset_adj",
                    owner="row_offset_adj_sink_fpr",
                ),
            ),
        ),
    )
    return _apply_model_patch(source_text, model, patched)


def _patch_product_local_materialize(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or model.product_local != "col_offset":
        return None
    if re.search(r"(?m)^\s*f32\s+col_offset_product_fpr\s*;", model.function_text):
        return None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        ("col_offset",),
        "f32 col_offset_product_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None:
        return None
    replacement = (
        f"{model.product_def.indent}col_offset_product_fpr = "
        f"y_spacing * {product_expr};\n"
        f"{model.product_def.indent}col_offset = col_offset_product_fpr;"
    )
    patched = _replace_statement(model.function_text, model.product_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_product_col_cast_operand_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if not _is_live_col_offset_cast_product(model):
        return None
    assert model is not None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        ("col_offset",),
        "f32 col_cast_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not _is_live_col_offset_cast_product(model):
        return None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    replacement = (
        f"{model.product_def.indent}col_cast_owner_fpr = {product_expr};\n"
        f"{model.product_def.indent}col_offset = "
        "y_spacing * col_cast_owner_fpr;"
    )
    patched = _replace_statement(model.function_text, model.product_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_product_y_spacing_operand_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if not _is_live_col_offset_cast_product(model):
        return None
    assert model is not None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        ("y_spacing", "col_offset"),
        "f32 y_spacing_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not _is_live_col_offset_cast_product(model):
        return None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    replacement = (
        f"{model.product_def.indent}y_spacing_owner_fpr = y_spacing;\n"
        f"{model.product_def.indent}col_offset = "
        f"y_spacing_owner_fpr * {product_expr};"
    )
    patched = _replace_statement(model.function_text, model.product_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_product_combined_operand_owners(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if not _is_live_col_offset_cast_product(model):
        return None
    assert model is not None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        ("y_spacing", "col_offset"),
        "f32 y_spacing_owner_fpr;",
    )
    if patched is None:
        return None
    patched = _insert_decl_after_any(
        patched,
        ("col_offset",),
        "f32 col_cast_owner_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not _is_live_col_offset_cast_product(model):
        return None
    product_expr = _product_expr(model)
    if product_expr is None:
        return None
    replacement = (
        f"{model.product_def.indent}y_spacing_owner_fpr = y_spacing;\n"
        f"{model.product_def.indent}col_cast_owner_fpr = {product_expr};\n"
        f"{model.product_def.indent}col_offset = "
        "y_spacing_owner_fpr * col_cast_owner_fpr;"
    )
    patched = _replace_statement(model.function_text, model.product_def, replacement)
    return _apply_model_patch(source_text, model, patched)


def _is_live_col_offset_cast_product(
    model: _RowProductSourceModel | None,
) -> bool:
    if model is None or model.product_local != "col_offset":
        return False
    product_expr = _product_expr(model)
    if product_expr is None:
        return False
    return re.fullmatch(r"\(f32\)\s*col", product_expr.strip()) is not None


def _patch_product_col_offset_sink_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or not model.col_sink_uses:
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        ("col_offset", model.product_local),
        "f32 col_offset_sink_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or not model.col_sink_uses:
        return None
    sink = model.col_sink_uses[0]
    replacement = _sink_owner_replacement(
        sink,
        local="col_offset",
        owner="col_offset_sink_fpr",
    )
    patched = _replace_statement(model.function_text, sink, replacement)
    return _apply_model_patch(source_text, model, patched)


def _patch_product_handoff_late_owner(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if (
        model is None
        or model.product_handoff is None
        or not model.col_sink_uses
        or model.product_local == "col_offset"
    ):
        return None
    patched = _insert_decl_after_any(
        model.function_text,
        (model.product_local, "col_offset"),
        "f32 col_offset_product_late_fpr;",
    )
    if patched is None:
        return None
    model = _model_after_function_patch(source_text, function_span, patched)
    if model is None or model.product_handoff is None or not model.col_sink_uses:
        return None
    handoff = model.product_handoff
    sink = model.col_sink_uses[0]
    lines = model.function_text.splitlines(keepends=True)
    handoff_range = _statement_line_range(model.function_text, handoff)
    sink_range = _statement_line_range(model.function_text, sink)
    del lines[handoff_range[0]:handoff_range[1]]
    removed_before_sink = handoff_range[1] <= sink_range[0]
    insert_at = sink_range[0] - (handoff_range[1] - handoff_range[0] if removed_before_sink else 0)
    lines[insert_at:insert_at] = [
        f"{sink.indent}col_offset_product_late_fpr = {model.product_local};\n",
        f"{sink.indent}col_offset = col_offset_product_late_fpr;\n",
    ]
    patched = "".join(lines)
    return _apply_model_patch(source_text, model, patched)


def _patch_digit_guard_product_before_count(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or model.digit_count_call is None:
        return None
    spans = [model.product_def]
    if model.product_handoff is not None:
        spans.append(model.product_handoff)
    patched = _move_statement_block(
        model.function_text,
        spans,
        before=model.digit_count_call,
    )
    if patched is None:
        return None
    return _apply_model_patch(source_text, model, patched)


def _patch_digit_guard_row_scale_before_count(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None or model.digit_count_call is None:
        return None
    spans: list[_StatementSpan] = []
    rowf = _find_rowf_assignment(model.function_text)
    if rowf is not None:
        spans.append(rowf)
    spans.append(model.row_scaled_def)
    if model.row_adj_def is not None:
        spans.append(model.row_adj_def)
    patched = _move_statement_block(
        model.function_text,
        spans,
        before=model.digit_count_call,
    )
    if patched is None:
        return None
    return _apply_model_patch(source_text, model, patched)


def _patch_digit_guard_product_after_row_scale(
    source_text: str,
    function_span: Any,
) -> str | None:
    model = _extract_row_product_source_model(source_text, function_span)
    if model is None:
        return None
    anchor = model.row_adj_def or model.row_scaled_def
    spans = [model.product_def]
    if model.product_handoff is not None:
        spans.append(model.product_handoff)
    patched = _move_statement_block(
        model.function_text,
        spans,
        after=anchor,
    )
    if patched is None:
        return None
    return _apply_model_patch(source_text, model, patched)


def _patch_paired_recombine(
    source_text: str,
    function_span: Any,
    patchers: Sequence[Any],
) -> str | None:
    single_hunks: list[list[dict[str, Any]]] = []
    for index, patcher in enumerate(patchers):
        patched = patcher(source_text, function_span)
        if patched is None or patched == source_text:
            return None
        hunks = _source_hunks(
            source_text,
            patched,
            candidate_id=f"paired-input-{index}",
        )
        for previous in single_hunks:
            if not _hunks_non_overlapping(previous, hunks):
                return None
        single_hunks.append(hunks)
    return _apply_patchers_in_order(source_text, function_span, patchers)


def _patch_row_offset_owner_split(source_text: str, function_span: Any) -> str | None:
    function_text = source_text[function_span.sig_start:function_span.full_end]
    patched = _insert_decl_after(
        function_text,
        anchor_name="row_offset",
        declaration="f32 row_offset_owner_fpr;",
    )
    if patched is None:
        return None

    row_def_re = re.compile(
        r"(?m)^([ \t]*)row_offset\s*=\s*"
        r"HSD_JObjGetTranslationY\(\s*jobj2\s*\)\s*-\s*base\s*;\s*$"
    )
    if row_def_re.search(patched) is None:
        return None
    patched = row_def_re.sub(
        lambda match: (
            f"{match.group(0)}\n"
            f"{match.group(1)}row_offset_owner_fpr = row_offset;"
        ),
        patched,
        count=1,
    )

    scaled_re = re.compile(r"(?m)^([ \t]*)row_offset\s*\*=\s*rowf\s*;\s*$")
    if scaled_re.search(patched) is None:
        return None
    patched = scaled_re.sub(
        lambda match: f"{match.group(1)}row_offset = row_offset_owner_fpr * rowf;",
        patched,
        count=1,
    )
    return _replace_function_text(source_text, function_span, patched)


def _patch_product_owner_copy(source_text: str, function_span: Any) -> str | None:
    function_text = source_text[function_span.sig_start:function_span.full_end]
    patched = _insert_decl_after(
        function_text,
        anchor_name="col_offset_product_fpr",
        declaration="f32 col_offset_product_owner_fpr;",
    )
    if patched is None:
        return None

    product_re = re.compile(
        r"(?m)^([ \t]*)col_offset_product_fpr\s*=\s*"
        r"y_spacing\s*\*\s*col_cast_owner_fpr\s*;\s*\n"
        r"[ \t]*col_offset\s*=\s*col_offset_product_fpr\s*;\s*$"
    )
    if product_re.search(patched) is None:
        return None
    patched = product_re.sub(
        lambda match: (
            f"{match.group(1)}col_offset_product_fpr = "
            "y_spacing * col_cast_owner_fpr;\n"
            f"{match.group(1)}col_offset_product_owner_fpr = "
            "col_offset_product_fpr;\n"
            f"{match.group(1)}col_offset = col_offset_product_owner_fpr;"
        ),
        patched,
        count=1,
    )
    return _replace_function_text(source_text, function_span, patched)


def _patch_row_owner_product_interleave(
    source_text: str,
    function_span: Any,
) -> str | None:
    function_text = source_text[function_span.sig_start:function_span.full_end]
    patched = _insert_decl_after(
        function_text,
        anchor_name="row_offset",
        declaration="f32 row_offset_owner_fpr;",
    )
    if patched is None:
        return None

    block_re = re.compile(
        r"(?m)^([ \t]*)row_offset\s*=\s*"
        r"HSD_JObjGetTranslationY\(\s*jobj2\s*\)\s*-\s*base\s*;\s*\n"
        r"\s*\n"
        r"[ \t]*digit_count\s*=\s*mn_GetDigitCount\(\s*value\s*\)\s*;\s*\n"
        r"[ \t]*col_offset_product_fpr\s*=\s*"
        r"y_spacing\s*\*\s*col_cast_owner_fpr\s*;\s*\n"
        r"[ \t]*col_offset\s*=\s*col_offset_product_fpr\s*;\s*\n"
        r"[ \t]*rowf\s*=\s*\(f32\)\s*row\s*;\s*\n"
        r"[ \t]*row_offset\s*\*=\s*rowf\s*;\s*\n"
        r"[ \t]*row_offset_adj\s*=\s*row_offset\s*-\s*0\.4f\s*;\s*$"
    )
    if block_re.search(patched) is None:
        return None
    patched = block_re.sub(
        lambda match: (
            f"{match.group(1)}row_offset = "
            "HSD_JObjGetTranslationY(jobj2) - base;\n"
            f"{match.group(1)}row_offset_owner_fpr = row_offset;\n"
            f"{match.group(1)}col_offset_product_fpr = "
            "y_spacing * col_cast_owner_fpr;\n"
            f"{match.group(1)}col_offset = col_offset_product_fpr;\n"
            f"{match.group(1)}digit_count = mn_GetDigitCount(value);\n"
            f"{match.group(1)}rowf = (f32) row;\n"
            f"{match.group(1)}row_offset = row_offset_owner_fpr * rowf;\n"
            f"{match.group(1)}row_offset_adj = row_offset - 0.4f;"
        ),
        patched,
        count=1,
    )
    return _replace_function_text(source_text, function_span, patched)


def _remaining_blockers(
    ranked: Sequence[CandidateAssessment],
    focus_name: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for assessment in ranked:
        residual = assessment.residual or {}
        case = _case_value(residual)
        if case == "A" and "A" not in seen:
            target_reg = residual.get("target_reg", assessment.focus_expected)
            blocker_source = residual.get("blocker_source") or "row_offset"
            blockers.append({
                "case": "A",
                "focus_ig": residual.get(
                    "ig_idx",
                    assessment.focus_candidate_virtual
                    or assessment.focus_baseline_virtual,
                ),
                "blocker_ig": residual.get("blocker_ig"),
                "blocker_source": blocker_source,
                "focus": focus_name,
                "reason": (
                    f"f{target_reg} remains held by {blocker_source} "
                    f"interferer blocking the {focus_name} product"
                ),
                "focus_blocker_interference_present": residual.get(
                    "focus_blocker_interference_present"
                ),
            })
            seen.add("A")
        elif case == "C2" and "C2" not in seen:
            blockers.append({
                "case": "C2",
                "focus_ig": residual.get(
                    "ig_idx",
                    assessment.focus_candidate_virtual
                    or assessment.focus_baseline_virtual,
                ),
                "current_product_reg": residual.get(
                    "baseline_reg",
                    assessment.focus_actual,
                ),
                "target_reg": residual.get("target_reg", assessment.focus_expected),
                "working_mask": residual.get("working_mask"),
                "reason": (
                    residual.get("reason")
                    or "select-order progress moves product into sticky-pool "
                    "residual but loses protected expression hits"
                ),
            })
            seen.add("C2")
        if "C2" not in seen:
            swap_blocker = _expression_register_swap_blocker(
                assessment,
                focus_name=focus_name,
            )
            if swap_blocker is not None:
                blockers.append(swap_blocker)
                seen.add("C2")
    return blockers


def _expression_register_swap_blocker(
    assessment: CandidateAssessment,
    *,
    focus_name: str,
) -> dict[str, Any] | None:
    expression_score = assessment.candidate.expression_score
    if not isinstance(expression_score, Mapping):
        return None
    virtuals = _virtuals(expression_score)
    focus_key, _focus = _focus_entry(
        virtuals,
        ProtectedExpressionPolicy(
            focus_name=focus_name,
            focus_baseline_virtual=assessment.focus_baseline_virtual,
        ),
    )

    pairs: list[tuple[int, Mapping[str, Any], int, Mapping[str, Any]]] = []
    for left_key, left in sorted(virtuals.items()):
        left_actual = _int_or_none(left.get("actual"))
        left_expected = _int_or_none(left.get("expected"))
        if (
            left_actual is None
            or left_expected is None
            or left_actual == left_expected
        ):
            continue
        for right_key, right in sorted(virtuals.items()):
            if right_key <= left_key:
                continue
            right_actual = _int_or_none(right.get("actual"))
            right_expected = _int_or_none(right.get("expected"))
            if (
                right_actual is None
                or right_expected is None
                or right_actual == right_expected
            ):
                continue
            if left_actual == right_expected and right_actual == left_expected:
                pairs.append((left_key, left, right_key, right))

    if not pairs:
        return None

    for left_key, left, right_key, right in pairs:
        if focus_key == left_key:
            return _format_expression_register_swap_blocker(
                left_key, left, right_key, right, fallback_focus_name=focus_name
            )
        if focus_key == right_key:
            return _format_expression_register_swap_blocker(
                right_key, right, left_key, left, fallback_focus_name=focus_name
            )

    left_key, left, right_key, right = pairs[0]
    return _format_expression_register_swap_blocker(
        left_key, left, right_key, right, fallback_focus_name=focus_name
    )


def _format_expression_register_swap_blocker(
    focus_key: int,
    focus: Mapping[str, Any],
    paired_key: int,
    paired: Mapping[str, Any],
    *,
    fallback_focus_name: str,
) -> dict[str, Any]:
    focus_actual = _int_or_none(focus.get("actual"))
    focus_expected = _int_or_none(focus.get("expected"))
    paired_actual = _int_or_none(paired.get("actual"))
    paired_expected = _int_or_none(paired.get("expected"))
    paired_label = _anchor_label(paired) or str(
        paired.get("baseline_virtual", paired_key)
    )
    focus_label = _anchor_label(focus) or fallback_focus_name
    sticky_pool_bridge = _expression_sticky_pool_bridge(
        focus_key,
        focus,
        paired_key,
        paired,
        fallback_focus_name=fallback_focus_name,
    )
    return {
        "case": "C2",
        "focus": focus_label,
        "focus_ig": focus.get(
            "candidate_virtual",
            focus.get("baseline_virtual", focus_key),
        ),
        "paired_ig": paired.get(
            "candidate_virtual",
            paired.get("baseline_virtual", paired_key),
        ),
        "paired_source": paired_label,
        "current_focus_reg": focus_actual,
        "current_paired_reg": paired_actual,
        "target_reg": focus_expected,
        "paired_target_reg": paired_expected,
        "reason": (
            f"{focus_label} currently holds f{focus_actual} while "
            f"{paired_label} holds f{paired_actual}; their expected FPRs "
            "are swapped, indicating a Case C2 sticky-pool/source-order "
            "residual."
        ),
        "sticky_pool_bridge": sticky_pool_bridge,
    }


def _expression_sticky_pool_bridge(
    focus_key: int,
    focus: Mapping[str, Any],
    paired_key: int,
    paired: Mapping[str, Any],
    *,
    fallback_focus_name: str,
) -> dict[str, Any]:
    focus_anchor = _sticky_pool_anchor_summary(
        focus_key,
        focus,
        fallback_label=fallback_focus_name,
    )
    paired_anchor = _sticky_pool_anchor_summary(
        paired_key,
        paired,
        fallback_label=str(paired_key),
    )
    product_key, product = _product_anchor_for_sticky_bridge(
        focus_key,
        focus,
        paired_key,
        paired,
    )
    product_anchor = (
        _sticky_pool_anchor_summary(
            product_key,
            product,
            fallback_label=str(product_key),
        )
        if product is not None
        else None
    )
    product_actions = _product_operand_owner_actions(product_key, product)
    focus_upstream = focus_anchor["upstream_fpr_operands"]
    product_upstream = (
        product_anchor["upstream_fpr_operands"]
        if product_anchor is not None
        else []
    )
    follow_up_targets = _sticky_pool_follow_up_targets(
        focus_anchor=focus_anchor,
        paired_anchor=paired_anchor,
        product_anchor=product_anchor,
        product_actions=product_actions,
    )
    support_order_targets = _sticky_pool_select_order_target_groups(
        paired_anchor=paired_anchor,
        product_anchor=product_anchor,
    )
    row_fsubs_owner_repair = _sticky_pool_row_fsubs_owner_repair(
        paired_anchor,
        product_anchor=product_anchor,
    )
    blockers: list[str] = []
    if product_anchor is None:
        blockers.append("missing-product-anchor")
    if not product_actions:
        blockers.append("missing-source-actionable-product-operand-owners")
    if not focus_upstream:
        blockers.append("missing-focus-first-def-fpr-operands")

    return {
        "status": "ready" if product_anchor is not None else "partial",
        "derived_from": "expression_score",
        "diagnostic": (
            "expression anchors show a C2 register swap; follow-up must target "
            "product operand owners and sticky-pool pressure, not just the "
            "focus/paired order"
        ),
        "focus_anchor": focus_anchor,
        "paired_anchor": paired_anchor,
        "product_anchor": product_anchor,
        "focus_upstream_fpr_operands": focus_upstream,
        "product_upstream_fpr_operands": product_upstream,
        "source_actionable_product_operand_owner_actions": product_actions,
        "follow_up_targets": follow_up_targets,
        "support_order_policy": {
            "avoid_already_satisfied_as_main_route": True,
            "requires_baseline_unsatisfied_for_primary_route": True,
        },
        "select_order_target_groups": support_order_targets,
        **(
            {"row_fsubs_owner_repair": row_fsubs_owner_repair}
            if row_fsubs_owner_repair is not None
            else {}
        ),
        "pair_only_orders_to_avoid": [
            [
                focus_anchor["candidate_virtual"],
                paired_anchor["candidate_virtual"],
            ],
            [
                paired_anchor["candidate_virtual"],
                focus_anchor["candidate_virtual"],
            ],
        ],
        "blockers": blockers,
    }


def _sticky_pool_anchor_summary(
    key: int,
    entry: Mapping[str, Any],
    *,
    fallback_label: str,
) -> dict[str, Any]:
    source = _anchor_source(entry)
    first_def = _anchor_first_def(entry)
    operands = _first_def_operands(first_def)
    candidate_virtual = _int_or_none(entry.get("candidate_virtual"))
    if candidate_virtual is None:
        candidate_virtual = _int_or_none(entry.get("baseline_virtual", key))
    return {
        "label": _anchor_label(entry) or fallback_label,
        "baseline_virtual": _int_or_none(entry.get("baseline_virtual", key)),
        "candidate_virtual": candidate_virtual,
        "expected_reg": _int_or_none(entry.get("expected")),
        "actual_reg": _int_or_none(entry.get("actual")),
        "source_file": _str_or_none(source.get("source_file")),
        "source_line": _int_or_none(source.get("source_line")),
        "expression": _anchor_expression(entry),
        "first_def": (
            {
                "opcode": _str_or_none(first_def.get("opcode")),
                "operands": operands,
            }
            if first_def is not None
            else None
        ),
        "upstream_fpr_operands": _upstream_fpr_operand_ids(operands),
    }


def _anchor_source(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("candidate_source", "baseline_source", "source", "signature"):
        value = entry.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _anchor_expression(entry: Mapping[str, Any]) -> str | None:
    for key in ("expression", "source_expression"):
        value = entry.get(key)
        if value is not None:
            return str(value)
    for key in ("candidate_source", "baseline_source", "source", "signature"):
        value = entry.get(key)
        if not isinstance(value, Mapping):
            continue
        expression = value.get("expression")
        if expression is not None:
            return str(expression)
    return None


def _anchor_first_def(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = entry.get("first_def")
    if isinstance(value, Mapping):
        return value
    for key in ("candidate_source", "baseline_source", "source"):
        source = entry.get(key)
        if not isinstance(source, Mapping):
            continue
        value = source.get("first_def")
        if isinstance(value, Mapping):
            return value
    return None


def _first_def_operands(first_def: Mapping[str, Any] | None) -> list[str]:
    if first_def is None:
        return []
    raw = first_def.get("operands")
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


def _upstream_fpr_operand_ids(operands: Sequence[str]) -> list[int]:
    out: list[int] = []
    for operand in operands[1:]:
        match = re.fullmatch(r"f(\d+)", operand.strip())
        if match is None:
            continue
        out.append(int(match.group(1)))
    return out


def _upstream_fpr_operand_names(operands: Sequence[str]) -> list[str]:
    return [
        operand.strip()
        for operand in operands[1:]
        if re.fullmatch(r"f\d+", operand.strip()) is not None
    ]


def _product_anchor_for_sticky_bridge(
    focus_key: int,
    focus: Mapping[str, Any],
    paired_key: int,
    paired: Mapping[str, Any],
) -> tuple[int, Mapping[str, Any] | None]:
    if _is_product_expression_anchor(focus):
        return focus_key, focus
    if _is_product_expression_anchor(paired):
        return paired_key, paired
    return focus_key, None


def _is_product_expression_anchor(entry: Mapping[str, Any]) -> bool:
    expression = _anchor_expression(entry)
    if expression is not None and "y_spacing" in expression and "*" in expression:
        return True
    first_def = _anchor_first_def(entry)
    return bool(first_def and first_def.get("opcode") == "fmuls")


def _product_operand_owner_actions(
    product_key: int,
    product: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if product is None:
        return []
    expression = _anchor_expression(product)
    terms = _product_expression_terms(expression)
    if terms is None:
        return []
    left, right = terms
    product_ig = _int_or_none(product.get("candidate_virtual"))
    if product_ig is None:
        product_ig = _int_or_none(product.get("baseline_virtual", product_key))
    operands = _first_def_operands(_anchor_first_def(product))
    upstream_operands = _upstream_fpr_operand_names(operands)
    left_operand = upstream_operands[0] if len(upstream_operands) >= 1 else None
    right_operand = upstream_operands[1] if len(upstream_operands) >= 2 else None
    product_label = _anchor_label(product) or str(product_key)
    actions = [
        {
            "candidate_id": "product-y-spacing-owner-materialize",
            "family": "product_operand_ownership",
            "owner": "y_spacing_owner_fpr",
            "operand": left,
            "first_def_operand": left_operand,
            "product_anchor": product_label,
            "product_ig": product_ig,
            "source_actionability": "local-expression",
            "source_probe": "materialize y_spacing_owner_fpr before col_offset product",
        },
        {
            "candidate_id": "product-col-cast-owner-materialize",
            "family": "product_operand_ownership",
            "owner": "col_cast_owner_fpr",
            "operand": right,
            "first_def_operand": right_operand,
            "product_anchor": product_label,
            "product_ig": product_ig,
            "source_actionability": "local-expression",
            "source_probe": "materialize col_cast_owner_fpr before col_offset product",
        },
        {
            "candidate_id": "product-combined-operand-owners",
            "family": "product_operand_ownership",
            "owner": "y_spacing_owner_fpr + col_cast_owner_fpr",
            "operands": [left, right],
            "first_def_operands": upstream_operands,
            "product_anchor": product_label,
            "product_ig": product_ig,
            "source_actionability": "local-expression",
            "source_probe": "materialize both product operands before multiplying",
        },
    ]
    return actions


def _sticky_pool_select_order_target_groups(
    *,
    paired_anchor: Mapping[str, Any],
    product_anchor: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if product_anchor is None:
        return []
    product_ig = _int_or_none(product_anchor.get("candidate_virtual"))
    paired_ig = _int_or_none(paired_anchor.get("candidate_virtual"))
    support_operands = _unique_ints(product_anchor.get("upstream_fpr_operands", ()))
    support_before_product = [
        [support, product_ig]
        for support in support_operands
        if product_ig is not None
    ]
    product_before_support = [
        [product_ig, support]
        for support in support_operands
        if product_ig is not None
    ]
    product_before_paired = (
        [[product_ig, paired_ig]]
        if product_ig is not None and paired_ig is not None
        else []
    )
    groups: list[dict[str, Any]] = []
    if support_before_product:
        groups.append({
            "kind": "product-support-before-product",
            "target_pairs": support_before_product,
            "route_role": "verify-only-if-already-satisfied",
            "requires_baseline_unsatisfied": True,
        })
    if product_before_paired:
        groups.append({
            "kind": "row-col-crossing",
            "target_pairs": product_before_paired,
            "route_role": "primary-c2-pair",
            "requires_baseline_unsatisfied": True,
        })
    if product_before_support:
        groups.append({
            "kind": "product-before-support",
            "target_pairs": product_before_support,
            "route_role": "inverse-support-exploration",
            "requires_baseline_unsatisfied": True,
        })
    return groups


def _sticky_pool_row_fsubs_owner_repair(
    row_anchor: Mapping[str, Any],
    *,
    product_anchor: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    first_def = row_anchor.get("first_def")
    if not isinstance(first_def, Mapping):
        return None
    if first_def.get("opcode") != "fsubs":
        return None
    expression = str(row_anchor.get("expression") or "").strip()
    if _row_fsubs_call_minus_local(expression) is None:
        return None
    row_ig = _int_or_none(row_anchor.get("candidate_virtual"))
    if row_ig is None:
        return None
    expected = _int_or_none(row_anchor.get("expected_reg"))
    operands = first_def.get("operands")
    first_def_operands = list(operands) if isinstance(operands, list) else []
    return {
        "status": "candidate",
        "target_ig": row_ig,
        "expected_phys": expected,
        "source_name": row_anchor.get("label"),
        "first_def_opcode": "fsubs",
        "first_def_operands": first_def_operands,
        "source_expression": expression,
        "candidate_ids": [
            "row-fsubs-call-result-owner",
            "row-fsubs-owner-temp",
        ],
        "requires_expression_score_validation": True,
        **(
            {"paired_product_ig": _int_or_none(product_anchor.get("candidate_virtual"))}
            if isinstance(product_anchor, Mapping)
            else {}
        ),
    }


def _product_expression_terms(expression: str | None) -> tuple[str, str] | None:
    if expression is None:
        return None
    match = re.fullmatch(
        r"\s*(?P<left>y_spacing)\s*\*\s*(?P<right>\(f32\)\s*col)\s*",
        expression,
    )
    if match is None:
        return None
    return match.group("left"), match.group("right")


def _row_fsubs_call_minus_local(expression: str | None) -> tuple[str, str] | None:
    if expression is None:
        return None
    match = re.fullmatch(
        r"\s*(?P<call>HSD_JObjGetTranslationY\(\s*[A-Za-z_]\w*\s*\))"
        r"\s*-\s*(?P<base>[A-Za-z_]\w*)\s*",
        expression,
    )
    if match is None:
        return None
    return match.group("call"), match.group("base")


def _sticky_pool_follow_up_targets(
    *,
    focus_anchor: Mapping[str, Any],
    paired_anchor: Mapping[str, Any],
    product_anchor: Mapping[str, Any] | None,
    product_actions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    focus_ig = _int_or_none(focus_anchor.get("candidate_virtual"))
    paired_ig = _int_or_none(paired_anchor.get("candidate_virtual"))
    product_ig = (
        _int_or_none(product_anchor.get("candidate_virtual"))
        if product_anchor is not None
        else focus_ig
    )
    upstream = (
        list(product_anchor.get("upstream_fpr_operands", ()))
        if isinstance(product_anchor, Mapping)
        else []
    )
    target_virtuals = _unique_ints([*upstream, product_ig, focus_ig, paired_ig])
    owner_candidate_ids = [
        str(action["candidate_id"])
        for action in product_actions
        if action.get("candidate_id") is not None
    ]
    return [
        {
            "kind": "pressure_probe",
            "target_virtuals": target_virtuals,
            "pair_only": False,
            "why": (
                "test product operand pressure and pool admission before "
                "trying the swapped expression pair alone"
            ),
        },
        {
            "kind": "select_order_probe",
            "target_virtuals": target_virtuals,
            "pair_only": False,
            "avoid_pair_only_orders": [
                _not_none_ints([focus_ig, paired_ig]),
                _not_none_ints([paired_ig, focus_ig]),
            ],
        },
        {
            "kind": "force_probe",
            "target_virtuals": target_virtuals,
            "force_map": {
                str(key): value
                for key, value in (
                    (focus_ig, _int_or_none(focus_anchor.get("expected_reg"))),
                    (paired_ig, _int_or_none(paired_anchor.get("expected_reg"))),
                )
                if key is not None and value is not None
            },
            "support_virtuals": upstream,
            "pair_only": False,
        },
        {
            "kind": "source_generation",
            "family": "product_operand_ownership",
            "candidate_ids": owner_candidate_ids,
            "target_virtuals": target_virtuals,
            "pair_only": False,
        },
    ]


def _unique_ints(values: Sequence[Any]) -> list[int]:
    out: list[int] = []
    for value in values:
        converted = _int_or_none(value)
        if converted is None or converted in out:
            continue
        out.append(converted)
    return out


def _not_none_ints(values: Sequence[Any]) -> list[int]:
    return [
        converted
        for value in values
        if (converted := _int_or_none(value)) is not None
    ]


def _protected_required(assessment: CandidateAssessment | None) -> list[str]:
    if assessment is None or not assessment.candidate.expression_score:
        return []
    virtuals = _virtuals(assessment.candidate.expression_score)
    focus_key, _focus = _focus_entry(
        virtuals,
        ProtectedExpressionPolicy(
            focus_name="",
            focus_baseline_virtual=assessment.focus_baseline_virtual,
        ),
    )
    required: list[str] = []
    for _baseline, entry in _protected_entries(
        virtuals,
        _policy_from_assessment(assessment),
        focus_key,
    ):
        label = _anchor_label(entry)
        expected = _int_or_none(entry.get("expected"))
        if label is None:
            label = str(entry.get("baseline_virtual", "?"))
        if expected is None:
            required.append(label)
        else:
            required.append(f"{label} -> f{expected}")
    return required


def _policy_from_assessment(assessment: CandidateAssessment) -> ProtectedExpressionPolicy:
    return ProtectedExpressionPolicy(
        focus_name="",
        focus_baseline_virtual=assessment.focus_baseline_virtual,
    )


def _residual_rank(
    residual: Mapping[str, Any] | None,
    assessment: CandidateAssessment,
) -> int:
    case = _case_value(residual)
    if case in (None, "none"):
        return 5
    if case == "A":
        if not residual or residual.get("blocker_ig") in (None, _MISSING):
            return 4
        return 2
    if case == "C2":
        if assessment.focus_actual is not None and assessment.focus_expected is not None:
            if abs(assessment.focus_actual - assessment.focus_expected) <= 2:
                return 3
        return 1
    if "protected" in str(case).lower():
        return 0
    return 1


def _virtuals(expression_score: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    raw = (
        expression_score.get("virtuals")
        if isinstance(expression_score, Mapping)
        else {}
    )
    if not isinstance(raw, Mapping):
        return {}
    out: dict[int, Mapping[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, Mapping):
            continue
        baseline = _int_or_none(value.get("baseline_virtual", key))
        if baseline is None:
            continue
        out[baseline] = value
    return out


def _focus_entry(
    virtuals: Mapping[int, Mapping[str, Any]],
    policy: ProtectedExpressionPolicy,
) -> tuple[int | None, Mapping[str, Any] | None]:
    if policy.focus_baseline_virtual is not None:
        focus = virtuals.get(policy.focus_baseline_virtual)
        if focus is not None:
            return policy.focus_baseline_virtual, focus
    for baseline, entry in virtuals.items():
        if _anchor_matches_name(entry, policy.focus_name):
            return baseline, entry
    return None, None


def _protected_entries(
    virtuals: Mapping[int, Mapping[str, Any]],
    policy: ProtectedExpressionPolicy,
    focus_key: int | None,
) -> list[tuple[int, Mapping[str, Any]]]:
    protected_ids = policy.protected_baseline_virtuals
    out: list[tuple[int, Mapping[str, Any]]] = []
    for baseline, entry in virtuals.items():
        if protected_ids is not None:
            if baseline in protected_ids:
                out.append((baseline, entry))
            continue
        if focus_key is None or baseline != focus_key:
            out.append((baseline, entry))
    return out


def _false_positive_baselines(expression_score: Mapping[str, Any]) -> set[int]:
    raw_hits = expression_score.get("false_positive_virtual_id_hits", ())
    out: set[int] = set()
    if not isinstance(raw_hits, Sequence) or isinstance(raw_hits, (str, bytes)):
        return out
    for hit in raw_hits:
        if not isinstance(hit, Mapping):
            continue
        baseline = _int_or_none(hit.get("baseline_virtual"))
        if baseline is not None:
            out.add(baseline)
    return out


def _anchor_matches_name(entry: Mapping[str, Any], name: str) -> bool:
    if not name:
        return False
    for candidate in _anchor_names(entry):
        if candidate == name:
            return True
    return False


def _anchor_label(entry: Mapping[str, Any]) -> str | None:
    for name in _anchor_names(entry):
        if name:
            return name
    return None


def _anchor_names(entry: Mapping[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for key in ("name", "expression", "source_expression"):
        value = entry.get(key)
        if value is not None:
            names.append(str(value))
    for container_key in ("candidate_source", "baseline_source", "signature", "source"):
        container = entry.get(container_key)
        if not isinstance(container, Mapping):
            continue
        for key in ("name", "expression", "call_symbol"):
            value = container.get(key)
            if value is not None:
                names.append(str(value))
    return tuple(dict.fromkeys(names))


def _blocker_source_from_attribution(
    blocker_attribution: Mapping[str, Any] | None,
    blocker_ig: int | None,
) -> dict[str, Any] | None:
    if blocker_attribution is None or blocker_ig is None:
        return None
    raw_virtuals = blocker_attribution.get("virtuals")
    if isinstance(raw_virtuals, Mapping):
        iterable = raw_virtuals.values()
    elif (
        isinstance(raw_virtuals, Sequence)
        and not isinstance(raw_virtuals, (str, bytes))
    ):
        iterable = raw_virtuals
    else:
        return None
    for item in iterable:
        if not isinstance(item, Mapping):
            continue
        if _int_or_none(item.get("virtual", item.get("ig_idx"))) != blocker_ig:
            continue
        source = item.get("source")
        if not isinstance(source, Mapping):
            return None
        name = source.get("name") or source.get("expression")
        if name is None:
            return None
        return {
            "name": str(name),
            "confidence": _str_or_none(source.get("confidence")),
            "expression": _str_or_none(source.get("expression")),
            "first_def": source.get("first_def"),
        }
    return None


def _structural_guard_accepted(guard: Mapping[str, Any] | None) -> bool:
    if guard is None:
        return True
    accepted = guard.get("accepted")
    if accepted is None:
        return True
    return bool(accepted)


def _case_value(residual: Mapping[str, Any] | None) -> str | None:
    if not isinstance(residual, Mapping):
        return None
    raw = residual.get("case")
    if raw is None:
        return None
    value = getattr(raw, "value", raw)
    value = str(value)
    if value in {"A_BLOCKED", "A-blocked"}:
        return "A"
    if value in {"C2_STICKY_POOL", "C2-sticky-pool"}:
        return "C2"
    return value


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    converted = _int_or_none(value)
    return default if converted is None else converted


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
