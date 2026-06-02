"""Protocol definitions for the search substrate."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from src.search.artifact import CandidateArtifact
from src.search.types import (
    BackendCaps,
    Budget,
    ProducerHandle,
    ProducerStatus,
    SchedulePolicy,
    SearchContext,
    SearchResult,
    SourceSpec,
    SourceVariant,
    TargetSpec,
)


@runtime_checkable
class VariantSource(Protocol):
    """Protocol for a source of candidate variants."""

    def name(self) -> str:
        """Return the name of this source."""
        ...

    def seed(self, base: SourceSpec) -> None:
        """Initialize the source with a base specification."""
        ...

    def next_batch(self, n: int) -> list[SourceVariant]:
        """Return the next batch of candidate variants."""
        ...

    def observe(self, scored: list[CandidateArtifact]) -> None:
        """Observe the scoring of candidates to inform future batches."""
        ...


@runtime_checkable
class CompileBackend(Protocol):
    """Protocol for a compilation backend."""

    def name(self) -> str:
        """Return the name of this backend."""
        ...

    def capabilities(self) -> BackendCaps:
        """Return the capabilities of this backend."""
        ...

    def compile(
        self, variant: SourceVariant, *, want_pcdump: bool = False
    ) -> CandidateArtifact:
        """Compile a variant and return the artifact."""
        ...


@runtime_checkable
class ArtifactProducer(Protocol):
    """Protocol for a producer of candidate artifacts."""

    def name(self) -> str:
        """Return the name of this producer."""
        ...

    def start(
        self, base: SourceSpec, target: TargetSpec, budget: Budget
    ) -> ProducerHandle:
        """Start a producer job and return a handle."""
        ...

    def poll(self, handle: ProducerHandle) -> list[CandidateArtifact]:
        """Poll for new artifacts from a running producer job."""
        ...

    def status(self, handle: ProducerHandle) -> ProducerStatus:
        """Get the status of a producer job."""
        ...

    def stop(self, handle: ProducerHandle) -> None:
        """Stop a running producer job."""
        ...


@runtime_checkable
class ScorePipeline(Protocol):
    """Protocol for scoring and filtering candidates."""

    def score_byte(self, art: CandidateArtifact, target: TargetSpec) -> CandidateArtifact:
        """Score a candidate by byte-match percentage."""
        ...

    def should_escalate(self, art: CandidateArtifact, ctx: SearchContext) -> bool:
        """Determine if a candidate should be escalated for directed scoring."""
        ...

    def score_directed(
        self, art: CandidateArtifact, objective: object
    ) -> CandidateArtifact:
        """Score a candidate using directed metrics."""
        ...


@runtime_checkable
class Scheduler(Protocol):
    """Protocol for orchestrating a search run."""

    def run(
        self,
        *,
        sources: list[VariantSource],
        backends: list[CompileBackend],
        producers: list[ArtifactProducer],
        pipeline: ScorePipeline,
        target: TargetSpec,
        budget: Budget,
        policy: SchedulePolicy,
        progress: Callable[[dict], None] | None = None,
    ) -> SearchResult:
        """Run a search and return the result."""
        ...
