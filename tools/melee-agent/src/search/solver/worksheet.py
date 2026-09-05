"""§7 worksheet schema (verbatim field names) + serialization.

surrogate_confidence (spec §7 / finding rev2-6):
  "high"     iff the surrogate reproduces the FULL target vector for EVERY
             contested register AND the perturbation has a resolved source
             object with a tier-a C realization;
  "proposal" otherwise.
Driver contract: high = apply-now, proposal = investigate-first. §3 runs on both.

Schema extension (recorded in the plan's Deviations): pair_escalation carries a
`pair_hits` list so the §4.1 "no actionable pair" verdict and N7's "finds the
pair" criterion are reportable. All other keys are spec-verbatim.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


def classify_confidence(*, full_vector: bool, has_tier_a_source_object: bool) -> str:
    return "high" if (full_vector and has_tier_a_source_object) else "proposal"


@dataclass
class FilterSummary:
    candidates_generated: int
    rejected_a: int
    rejected_b: int
    flagged_c: int
    rejected_survival: int


@dataclass
class Candidate:
    rank: int
    perturbation: dict                  # {kind, target_ig, use_set?, edge?, order_move?}
    predicted_assignment_delta: dict
    c_realizations: list                # [{lever, source_object, confidence_tier}]
    surrogate_confidence: str           # "high" | "proposal"
    fidelity_gate: str = "pending"


@dataclass
class PairEscalation:
    ran: bool
    reason: str
    frontier_size: int
    frontier: list = field(default_factory=list)
    pair_hits: list = field(default_factory=list)   # recorded schema extension


@dataclass
class Worksheet:
    function: str
    class_id: int
    g1_rate: float
    force_phys_target: dict
    reachable: bool
    filter_summary: FilterSummary
    candidates: list                    # [Candidate | dict]
    tooling_leads: list
    window_order: list
    pair_escalation: PairEscalation
    enumeration_truncated: bool
    evals_per_kind: dict                # {node-add, edge, order}

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "class_id": self.class_id,
            "g1_rate": self.g1_rate,
            "force_phys_target": self.force_phys_target,
            "reachable": self.reachable,
            "filter_summary": asdict(self.filter_summary),
            "candidates": [c if isinstance(c, dict) else asdict(c)
                           for c in self.candidates],
            "tooling_leads": list(self.tooling_leads),
            "window_order": list(self.window_order),
            "pair_escalation": asdict(self.pair_escalation),
            "enumeration_truncated": self.enumeration_truncated,
            "evals_per_kind": dict(self.evals_per_kind),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
