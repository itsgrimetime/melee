"""Contracts and Pareto reduction for closed-world delta minimization."""

from .contracts import (
    AxisDistances,
    CandidateProfile,
    DeltaMinimizeError,
    ParetoGroup,
    ParetoSummary,
)
from .pareto import dominates, reduce_pareto

__all__ = [
    "AxisDistances",
    "CandidateProfile",
    "DeltaMinimizeError",
    "ParetoGroup",
    "ParetoSummary",
    "dominates",
    "reduce_pareto",
]
