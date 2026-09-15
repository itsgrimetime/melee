"""Contracts and Pareto reduction for closed-world delta minimization."""

from .contracts import (
    AxisDistances,
    CandidateProfile,
    DeltaMinimizeError,
    ParetoGroup,
    ParetoSummary,
)
from .namespace_review import (
    NamespaceArtifact,
    NamespaceReviewRequest,
    ReviewedNamespaceBinding,
    ReviewedNamespaces,
    load_review_request,
    load_reviewed_namespaces,
    resolve_reviewed_map,
    seal_namespace_review,
)
from .pareto import dominates, reduce_pareto
from .render import parse_donor_overrides, render_delta_minimize_text
from .run import (
    DeltaMinimizeBackends,
    DeltaMinimizeConfig,
    DeltaMinimizeResult,
    run_delta_minimize,
)

__all__ = [
    "AxisDistances",
    "CandidateProfile",
    "DeltaMinimizeError",
    "DeltaMinimizeBackends",
    "DeltaMinimizeConfig",
    "DeltaMinimizeResult",
    "NamespaceArtifact",
    "NamespaceReviewRequest",
    "ParetoGroup",
    "ParetoSummary",
    "ReviewedNamespaceBinding",
    "ReviewedNamespaces",
    "dominates",
    "load_review_request",
    "load_reviewed_namespaces",
    "parse_donor_overrides",
    "reduce_pareto",
    "render_delta_minimize_text",
    "resolve_reviewed_map",
    "run_delta_minimize",
    "seal_namespace_review",
]
