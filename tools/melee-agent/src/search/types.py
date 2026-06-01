"""Value types for the search substrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class SourceVariant:
    """A candidate source variant to compile."""

    source_text: str
    provenance: Any  # artifact.Provenance | None


@dataclass(frozen=True)
class SourceSpec:
    """Specification for a search problem base source."""

    base_source: str
    target: TargetSpec


@dataclass(frozen=True)
class TargetSpec:
    """Specification of the target function being matched."""

    function: str
    unit: str
    expected_obj: Path


@dataclass(frozen=True)
class Budget:
    """Resource budget for a search run."""

    max_iters: int | None = None
    max_seconds: float | None = None


@dataclass(frozen=True)
class BackendCaps:
    """Capabilities of a compile backend."""

    location: Literal["local", "remote"]
    parallelism: int
    supports_pcdump: bool


@dataclass(frozen=True)
class ProducerHandle:
    """Handle to a running producer job."""

    producer_name: str
    job_ids: list[str]


@dataclass(frozen=True)
class ProducerStatus:
    """Status of a producer job."""

    state: Literal["running", "drained", "failed"]
    detail: str = ""


@dataclass
class SearchContext:
    """Context accumulated during a search run."""

    iters_done: int = 0
    best_byte_score: int | None = None


@dataclass(frozen=True)
class SchedulePolicy:
    """Policy controlling search scheduling decisions."""

    batch_size: int = 16
    promote_top_k: int = 8
    max_retries: int = 2
    route_pcdump_to_capable_only: bool = True


@dataclass
class SearchResult:
    """Result of a search run."""

    best: list = field(default_factory=list)  # list[CandidateArtifact]
    matched: Any = None  # CandidateArtifact | None
    accounting: dict = field(default_factory=dict)
