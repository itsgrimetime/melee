"""Immutable data contracts for delta minimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class AxisDistances:
    """Lexicographically compared distance tuple for each objective axis."""

    opcode: tuple[int, int]
    color: tuple[int, int, int, int, int, int]
    objobjects: tuple[int, int]
    stack_homes: tuple[int, int, int, int]

    @classmethod
    def zero(cls) -> AxisDistances:
        return cls((0, 0), (0, 0, 0, 0, 0, 0), (0, 0), (0, 0, 0, 0))

    def to_dict(self) -> dict[str, list[int]]:
        return {
            "opcode": list(self.opcode),
            "color": list(self.color),
            "objobjects": list(self.objobjects),
            "stack_homes": list(self.stack_homes),
        }


@dataclass(frozen=True)
class CandidateProfile:
    """Complete scoring evidence for one enumerated candidate.

    ``viable`` means compilation succeeded and the requested function exists in
    the candidate's pcdump. Structural opcode/checkdiff consistency is
    validated before a complete profile reaches the reducer.
    """

    candidate_id: str
    mask: int
    source_hash: str
    source_path: str
    viable: bool
    compile_status: str
    axes: AxisDistances | None
    complete: bool
    exact_object_match: bool = False
    blockers: tuple[str, ...] = ()
    changed_bytes_from_left: int = 0
    changed_bytes_from_right: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "mask": self.mask,
            "source_hash": self.source_hash,
            "source_path": self.source_path,
            "viable": self.viable,
            "compile_status": self.compile_status,
            "axes": None if self.axes is None else self.axes.to_dict(),
            "complete": self.complete,
            "exact_object_match": self.exact_object_match,
            "blockers": list(self.blockers),
            "changed_bytes_from_left": self.changed_bytes_from_left,
            "changed_bytes_from_right": self.changed_bytes_from_right,
        }


class DeltaMinimizeError(RuntimeError):
    """A fail-closed delta-minimization error with structured details."""

    def __init__(self, reason: str, details: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "details": self.details}


@dataclass(frozen=True)
class ParetoGroup:
    """Raw and directionally minimized candidates for one objective vector."""

    objective_vector: AxisDistances
    candidate_ids: tuple[str, ...]
    minimal_from_left: tuple[str, ...]
    minimal_from_right: tuple[str, ...]
    representative: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_vector": self.objective_vector.to_dict(),
            "candidate_ids": list(self.candidate_ids),
            "minimal_from_left": list(self.minimal_from_left),
            "minimal_from_right": list(self.minimal_from_right),
            "representative": self.representative,
        }


@dataclass(frozen=True)
class ParetoSummary:
    """Exact reduction result after all viable candidate evidence completes."""

    status: str
    candidate_ids: tuple[str, ...]
    groups: tuple[ParetoGroup, ...]
    best_next: str | None
    exact_match_candidate_ids: tuple[str, ...]
    joint_solutions: tuple[str, ...]
    joint_zero_all_candidate_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_ids": list(self.candidate_ids),
            "groups": [group.to_dict() for group in self.groups],
            "best_next": self.best_next,
            "exact_match_candidate_ids": list(self.exact_match_candidate_ids),
            "joint_solutions": list(self.joint_solutions),
            "joint_zero_all_candidate_ids": list(self.joint_zero_all_candidate_ids),
        }
