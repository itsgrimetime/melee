"""Contracts and Pareto reduction for closed-world delta minimization."""

from .contracts import (
    AxisDistances,
    CandidateProfile,
    DeltaMinimizeError,
    ParetoGroup,
    ParetoSummary,
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
    "ParetoGroup",
    "ParetoSummary",
    "dominates",
    "parse_donor_overrides",
    "reduce_pareto",
    "render_delta_minimize_text",
    "run_delta_minimize",
]
