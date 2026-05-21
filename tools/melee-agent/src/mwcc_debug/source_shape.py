"""Shared dataclasses for source-shape suggestion tooling."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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


@dataclass(frozen=True)
class CandidateScore:
    """Verification result for one candidate."""

    candidate_id: str
    compile_ok: bool
    checkdiff_pct: Optional[float]
    checkdiff_delta: Optional[float]
    pcdump_score_delta: Optional[float]
    diagnostics_path: Optional[Path]
    candidate_size: int = 0
    helper_param_count: int = 0


@dataclass
class SourceShapeReport:
    """Full report produced by suggest-inlines."""

    function: str
    candidates: list[InlineCandidate] = field(default_factory=list)
    patches: list[CandidatePatch] = field(default_factory=list)
    scores: list[CandidateScore] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def accepted_candidates(self) -> list[InlineCandidate]:
        return [c for c in self.candidates if not c.is_rejected]

    @property
    def rejected_candidates(self) -> list[InlineCandidate]:
        return [c for c in self.candidates if c.is_rejected]


def rank_scores(scores: list[CandidateScore]) -> list[CandidateScore]:
    """Rank verification results. Higher deltas are better."""

    def key(score: CandidateScore) -> tuple:
        check_delta = score.checkdiff_delta
        pcdump_delta = score.pcdump_score_delta
        return (
            0 if score.compile_ok else 1,
            -(check_delta if check_delta is not None else -9999.0),
            -(pcdump_delta if pcdump_delta is not None else -9999.0),
            score.candidate_size,
            score.helper_param_count,
            score.candidate_id,
        )

    return sorted(scores, key=key)
