from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Verdict = Literal[
    "lever",
    "fuzzy_only",
    "neutral",
    "unsupported",
    "deinline_failed",
]
VERDICTS: tuple[str, ...] = (
    "lever",
    "fuzzy_only",
    "neutral",
    "unsupported",
    "deinline_failed",
)
ExpansionForm = Literal["value_expr", "statement_splice", "scalar_assignment_splice"]


@dataclass(frozen=True)
class InlineDef:
    name: str
    def_location: Literal["tu", "header"]
    def_file: str
    is_static: bool
    return_class: Literal["void", "scalar", "pointer", "struct"]
    body_kind: Literal["single_return_expr", "multi_statement"]
    params: list[tuple[str, str]]
    body_text: str
    n_statements: int


@dataclass(frozen=True)
class CallSite:
    function: str
    byte_start: int
    byte_end: int
    args: list[str]


@dataclass(frozen=True)
class DeinlineResult:
    ok: bool
    expansion_form: ExpansionForm | None
    new_source: str | None
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class ScoreResult:
    compiled: bool
    baseline_pct: float | None
    deinlined_pct: float | None
    delta_fuzzy: float | None
    baseline_ndl: int | None
    deinlined_ndl: int | None
    delta_struct: int | None
    error: str | None = None
    evidence: dict[str, str] | None = None


@dataclass(frozen=True)
class LeverageRecord:
    run_id: str
    function: str
    unit: str
    inline_name: str
    def_location: str
    def_file: str
    is_static: bool
    n_call_sites: int
    baseline_pct: float | None
    deinlined_pct: float | None
    delta_fuzzy: float | None
    baseline_ndl: int | None
    deinlined_ndl: int | None
    delta_struct: int | None
    verdict: Verdict
    expansion_form: str | None
    shape_return: str
    shape_body: str
    shape_args: list[str]
    n_statements: int
    error: str | None
    evidence: dict[str, str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_row(self) -> dict:
        import json

        row = asdict(self)
        row["is_static"] = 1 if self.is_static else 0
        row["shape_args"] = json.dumps(self.shape_args)
        row.pop("evidence", None)
        return row
