"""Tier-1 scoring pipeline: byte-distance scoring and default scheduling policy."""

from __future__ import annotations

from dataclasses import replace

from src.search.adapters import ByteScorer
from src.search.artifact import CandidateArtifact
from src.search.types import TargetSpec, SearchContext, SchedulePolicy


def DefaultSchedulePolicy() -> SchedulePolicy:
    return SchedulePolicy()


class ByteScorePipeline:
    """Tier-1 scoring pipeline using byte-distance scorer."""

    def __init__(self, scorer: ByteScorer):
        self._scorer = scorer

    def score_byte(self, art: CandidateArtifact, target: TargetSpec) -> CandidateArtifact:
        """Score a candidate by byte distance. Returns artifact with score or score_failed status."""
        if art.object_path is None:
            return replace(art, status="score_failed")
        dist = self._scorer.byte_distance(art.object_path, target)
        return replace(art, byte_score=dist, status="ok")

    def should_escalate(self, art: CandidateArtifact, ctx: SearchContext) -> bool:
        """Tier-1 spec: no escalation to directed scoring."""
        return False

    def score_directed(self, art, objective):
        """Tier-2 directed scoring is deferred to a later spec."""
        raise NotImplementedError("tier-2 directed scoring is a later spec")
