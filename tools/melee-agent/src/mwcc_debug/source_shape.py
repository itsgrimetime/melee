"""Shared dataclasses for source-shape suggestion tooling."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class SourceAnchor:
    """A source range plus the diagnostic fact that selected it."""

    function: str
    scope_path: tuple[str, ...]
    byte_range: tuple[int, int]
    line_range: tuple[int, int]
    kind: str
    reason: str
    virtuals: tuple[int, ...] = ()


@dataclass(frozen=True)
class InlineCandidate:
    """One possible source-shape rewrite."""

    candidate_id: str
    kind: str
    anchor: SourceAnchor
    helper_name: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    source_excerpt: str
    rejection_reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_rejected(self) -> bool:
        return self.rejection_reason is not None


@dataclass(frozen=True)
class CandidatePatch:
    """A concrete source rewrite for one accepted candidate."""

    candidate_id: str
    patched_source: str
    summary: str
    touched_ranges: tuple[tuple[int, int], ...]
    hunk: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateCopyTrace:
    """Copy-lifetime summary attached to a verified source candidate."""

    from_virtual: Optional[int]
    to_virtual: Optional[int]
    status: str
    likely_cause: str
    first_copy_pass: Optional[str] = None
    last_copy_pass: Optional[str] = None
    first_copy_block: Optional[int] = None
    last_copy_block: Optional[int] = None
    first_absent_pass: Optional[str] = None
    transform_category: Optional[str] = None
    interest_reasons: tuple[str, ...] = ()
    note: Optional[str] = None


@dataclass(frozen=True)
class CandidateCopyTraceSet:
    """Display-focused subset plus the total raw trace count."""

    traces: tuple[CandidateCopyTrace, ...]
    total_count: int
    raw_traces: tuple[CandidateCopyTrace, ...] = ()

    @property
    def omitted_count(self) -> int:
        return max(0, self.total_count - len(self.traces))


@dataclass(frozen=True)
class CandidateScore:
    """Verification result for one candidate."""

    candidate_id: str
    compile_ok: bool
    checkdiff_pct: Optional[float]
    checkdiff_delta: Optional[float]
    pcdump_score_delta: Optional[float]
    diagnostics_path: Optional[Path]
    status: str = "scored"
    score_reason: Optional[str] = None
    checkdiff_baseline_pct: Optional[float] = None
    candidate_size: int = 0
    helper_param_count: int = 0
    copy_traces: tuple[CandidateCopyTrace, ...] = ()
    copy_trace_highlights: tuple[CandidateCopyTrace, ...] = ()
    copy_trace_total_count: int = 0
    copy_trace_omitted_count: int = 0
    score: int | None = None
    target_score: dict[str, Any] | None = None
    expression_score: dict[str, Any] | None = None
    structural_guard: dict[str, Any] | None = None
    structural_guard_error: str | None = None
    source_file: str | None = None
    source_retained: str | None = None
    pcdump_path: str | None = None
    score_command: str | None = None
    score_returncode: int | None = None
    score_stderr: str | None = None
    error: str | None = None
    score_error_kind: str | None = None
    terminal_safe: bool | None = None
    full_unit_source: bool = False
    target_matched: int | None = None
    target_targeted: int | None = None
    target_virtual_distance: int | None = None
    expression_matched: int | None = None
    expression_targeted: int | None = None
    expression_virtual_distance: int | None = None
    blockers: tuple[dict[str, Any], ...] = ()
    source_hunks: tuple[dict[str, Any], ...] = ()


def _unique_reasons(reasons: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    for reason in reasons:
        if reason and reason not in out:
            out.append(reason)
    return tuple(out)


def _removed_before_coloring(trace: CandidateCopyTrace) -> bool:
    if trace.likely_cause == "removed-before-coloring":
        return True
    if trace.transform_category in {
        "copy-eliminated-before-coloring",
        "copy-propagation-or-dead-copy",
        "copy-rewritten-before-coloring",
    }:
        return True
    return False


def _disappears_after_coloring(trace: CandidateCopyTrace) -> bool:
    return trace.first_absent_pass is not None and not _removed_before_coloring(trace)


def summarize_candidate_copy_traces(
    traces: Iterable[CandidateCopyTrace],
    *,
    max_traces: int = 12,
    priority_virtuals: tuple[int, ...] = (),
    priority_blocks: tuple[int, ...] = (),
) -> CandidateCopyTraceSet:
    """Select candidate-relevant copy traces for human output.

    The full candidate pcdump can introduce many incidental copies after a
    source rewrite. For source-shape candidates, the most useful subset is
    usually copies touching the candidate's source virtual or patched block,
    then dominant source virtuals fanning out to new temps, then copies whose
    visible `mr` disappears before allocator output.
    """
    trace_tuple = tuple(traces)
    if not trace_tuple:
        return CandidateCopyTraceSet(traces=(), total_count=0)

    removed_sources = Counter(
        trace.from_virtual for trace in trace_tuple
        if trace.from_virtual is not None and _removed_before_coloring(trace)
    )
    dominant_source: Optional[int] = None
    if removed_sources:
        [(candidate_source, count), *rest] = removed_sources.most_common()
        if count > 1 and (not rest or rest[0][1] < count):
            dominant_source = candidate_source

    priority_set = set(priority_virtuals)
    priority_block_set = set(priority_blocks)
    annotated: list[CandidateCopyTrace] = []
    for trace in trace_tuple:
        reasons = list(trace.interest_reasons)
        if (
            trace.from_virtual in priority_set
            or trace.to_virtual in priority_set
        ):
            reasons.append("priority-virtual")
        if (
            trace.first_copy_block in priority_block_set
            or trace.last_copy_block in priority_block_set
        ):
            reasons.append("patch-local-block")
        if (
            dominant_source is not None
            and trace.from_virtual == dominant_source
        ):
            reasons.append("dominant-source-virtual")
        if _removed_before_coloring(trace):
            reasons.append("removed-before-coloring")
        elif _disappears_after_coloring(trace):
            reasons.append("copy-disappears-after-coloring")
        annotated.append(replace(
            trace,
            interest_reasons=_unique_reasons(reasons),
        ))

    interesting = [
        trace for trace in annotated
        if trace.interest_reasons
    ]
    selected = interesting or annotated

    def key(
        trace: CandidateCopyTrace,
    ) -> tuple[int, int, int, int, int, int, int]:
        return (
            0 if "priority-virtual" in trace.interest_reasons else 1,
            0 if "patch-local-block" in trace.interest_reasons else 1,
            0 if _removed_before_coloring(trace) else 1,
            0 if "dominant-source-virtual" in trace.interest_reasons else 1,
            0 if "copy-disappears-after-coloring" in trace.interest_reasons else 1,
            -1 if trace.to_virtual is None else trace.to_virtual,
            -1 if trace.from_virtual is None else trace.from_virtual,
        )

    selected = sorted(selected, key=key)[:max_traces]
    return CandidateCopyTraceSet(
        traces=tuple(selected),
        total_count=len(trace_tuple),
        raw_traces=tuple(annotated),
    )


@dataclass
class SourceShapeReport:
    """Full report produced by suggest-inlines."""

    function: str
    candidates: list[InlineCandidate] = field(default_factory=list)
    patches: list[CandidatePatch] = field(default_factory=list)
    scores: list[CandidateScore] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    status: str = "ok"
    kind: Optional[str] = None
    family_id: Optional[str] = None
    terminal: bool = False
    terminal_reason: Optional[str] = None
    terminal_blocker: Optional[str] = None
    terminal_blockers: list[dict[str, object]] = field(default_factory=list)
    score_mode: Optional[str] = None
    score_output_dir: Optional[str] = None
    score_rows: list[dict[str, Any]] = field(default_factory=list)
    terminal_summary: dict[str, Any] | None = None
    source_model_proof: dict[str, Any] | None = None

    @property
    def accepted_candidates(self) -> list[InlineCandidate]:
        return [c for c in self.candidates if not c.is_rejected]

    @property
    def rejected_candidates(self) -> list[InlineCandidate]:
        return [c for c in self.candidates if c.is_rejected]


def rank_scores(scores: list[CandidateScore]) -> list[CandidateScore]:
    """Rank verification results. Higher deltas are better."""

    def has_score_source(score: CandidateScore) -> bool:
        return any(
            value is not None
            for value in (
                score.score,
                score.target_score,
                score.expression_score,
                score.structural_guard,
                score.score_returncode,
                score.source_retained,
                score.pcdump_path,
            )
        )

    def structural_guard_accepted(score: CandidateScore) -> bool:
        guard = score.structural_guard
        return isinstance(guard, dict) and bool(guard.get("accepted"))

    def score_source_key(score: CandidateScore) -> tuple:
        targeted = score.target_targeted or 0
        matched = score.target_matched or 0
        exact_target = targeted > 0 and matched >= targeted
        expression_distance = (
            score.expression_virtual_distance
            if score.expression_virtual_distance is not None
            else 999999
        )
        target_distance = (
            score.target_virtual_distance
            if score.target_virtual_distance is not None
            else 999999
        )
        error_rank = 0 if score.compile_ok and not score.error else 1
        return (
            error_rank,
            0 if exact_target else 1,
            -(score.expression_matched or 0),
            -(score.target_matched or 0),
            expression_distance,
            target_distance,
            0 if structural_guard_accepted(score) else 1,
            score.candidate_size,
            score.candidate_id,
        )

    def key(score: CandidateScore) -> tuple:
        if has_score_source(score):
            return (0, *score_source_key(score))
        check_delta = score.checkdiff_delta
        pcdump_delta = score.pcdump_score_delta
        return (
            1,
            0 if score.compile_ok else 1,
            -(check_delta if check_delta is not None else -9999.0),
            -(pcdump_delta if pcdump_delta is not None else -9999.0),
            score.candidate_size,
            score.helper_param_count,
            score.candidate_id,
        )

    return sorted(scores, key=key)
