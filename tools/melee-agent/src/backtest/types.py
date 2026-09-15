from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Optional

LEVER_CLASSES: tuple[str, ...] = (
    "embedded_assign_temp", "hoist_to_local", "split_local", "retype",
    "struct_overlay", "literal_vs_named", "decl_reorder",
    "count_down_or_compare_reuse", "inline_arg_or_schedule", "backend_coloring",
    "other",
)

AdvisoryVerdict = Literal["names-lever", "hints-adjacent", "silent-or-wrong"]
GenerativeVerdict = Literal["byte-match-reproduced", "improved-toward", "no-progress"]
AgentVerdict = Literal["matched", "improved", "stuck"]
CaseVerdict = Literal["SOLVED-BY-TOOLING", "PARTIAL", "GAP"]


@dataclass
class Case:
    function: str
    c_sha: str
    cprev_sha: str
    unit: str
    file: str
    ground_truth_diff: str
    lever_locus: str
    author: str
    provenance: str
    lever_class: str
    baseline_pct: Optional[float] = None
    baseline_ndl: Optional[int] = None
    target_pct: Optional[float] = None
    target_ndl: Optional[int] = None

    @property
    def case_id(self) -> str:
        return hashlib.sha256(f"{self.c_sha}\x00{self.function}".encode()).hexdigest()[:16]

    @property
    def target_ndl_is_zero(self) -> bool:
        return self.target_ndl == 0


@dataclass
class CaseResult:
    case_id: str
    advisory: Optional[AdvisoryVerdict] = None
    generative: Optional[GenerativeVerdict] = None
    agent: Optional[AgentVerdict] = None
    rollup: Optional[CaseVerdict] = None
    evidence: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = dict(self.__dict__)
        d["evidence"] = json.dumps(self.evidence)
        return d
