"""Frozen dataclass contracts for the directed search layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DirectedObjective:
    """Specifies what the directed search is trying to achieve."""

    search_target: Any  # TargetSpec | None
    role_target: Any  # role descriptor | None
    baseline_compile: Any  # CompileSpec | None
    baseline_pcdump_path: Any  # Path | None
    baseline_source_hash: str
    class_id: int
    objective_iter_by_original_ig: dict
    proof_force_phys: dict


@dataclass(frozen=True)
class DirectedSearchState:
    """Immutable snapshot of directed search state at one iteration."""

    prev_state: Any  # DirectedSearchState | None
    history: tuple
    last_lever: Any  # mutator key | None
    current_best: Any  # CandidateArtifact | None
    state_id: str


@dataclass(frozen=True)
class DirectedDiagnosis:
    """Diagnosis produced by analysing a pcdump diff."""

    case: Any  # str | None
    target_igs: Any  # list[int] | None
    source_idea: Any  # str | None
    coalesce_pair: Any  # tuple[int, int] | None
    mutator_key: Any  # str | None
    resolved_anchor: Any  # str | None
    analysis_valid: bool
    actionable: bool
    invalid_reason: Any  # str | None


@dataclass(frozen=True)
class DirectedMeta:
    """Metadata attached to a candidate produced by the directed layer."""

    candidate_id: str
    source_hash: str
    iteration: int
    parent_id: Any  # str | None
    parent_state_id: Any  # str | None
    valid: bool
    invalid_reason: Any  # str | None
    case: Any  # str | None
    label: Any  # str | None
    # --- GATE SIGNAL (Codex round 4 "Fix A" — phys-match) ---
    # displacement := phys_match_fraction (|satisfied| / total); 1.0 = full swap.
    # order_distance := phys_mismatch_count (blocked + abstained); 0 = the win.
    # These are the ONLY fields the gate reads. They are NOT the old
    # iter-ordering metric (which is demoted to the iter_* diagnostic fields).
    order_distance: int
    displacement: float
    displacement_delta: float
    reanchor_matched: int
    reanchor_total: int
    diagnosis_chars: int
    applied_mutator: Any  # str | None
    directed_scalar: float
    proof_assignments: Any = None  # dict | None
    byte_score: Any = None  # int | None
    checkdiff_gate: Any = None  # str | None
    # --- ATTRIBUTION INTEGRITY (Codex round 4 P0) ---
    # True when applied_mutator came from a NON-actionable (var_name=None blind
    # decl-pair) diagnosis with no causal link to the divergence. The gate
    # treats a non_actionable candidate as UNATTRIBUTED so a no-op can never
    # satisfy the attribution requirement.
    non_actionable: bool = False
    # --- DIAGNOSTIC TELEMETRY ONLY (the OLD iter-ordering metric) ---
    # Kept for inspection/characterization; NEVER consulted by the gate.
    iter_order_distance: Any = None  # int | None
    iter_displacement: Any = None  # float | None


@dataclass(frozen=True)
class DirectedScoringCall:
    """Carries an objective and parent state into the scoring pipeline."""

    objective: Any  # DirectedObjective | None
    parent_state: Any  # DirectedSearchState | None


@dataclass(frozen=True)
class DirectedSchedulerConfig:
    """Configuration for the directed scheduler."""

    objective: Any  # DirectedObjective | None
    score_pipeline: Any  # scoring pipeline | None
    backend: Any  # backend | None
    plateau_n: int
