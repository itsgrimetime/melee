"""Contracts and Pareto reduction for closed-world delta minimization."""

from .contracts import (
    AxisDistances,
    CandidateProfile,
    DeltaMinimizeError,
    ParetoGroup,
    ParetoSummary,
)
from .pareto import dominates, reduce_pareto
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
    "reduce_pareto",
    "run_delta_minimize",
]
