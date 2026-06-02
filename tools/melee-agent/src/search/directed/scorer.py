"""DirectedScorePipeline: tier-2 directed scorer.

Scores a compiled candidate against its PARENT state (so batch siblings don't
contaminate each other), gated by a hardened validity check, returning a
DirectedMeta.  This pipeline is PURE: score_directed never mutates any global
state, call args, or parent state.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Optional

from src.search.directed.contracts import (
    DirectedMeta,
    DirectedScoringCall,
)
from src.search.directed.metric import (
    candidate_iter_by_original_ig,
    displacement,
    order_distance,
)


# ---------------------------------------------------------------------------
# Mutator keys that count as "order-change" edits for classify_progress.
# ---------------------------------------------------------------------------

ORDER_CHANGE_MUTATORS: frozenset = frozenset({"reorder_local_decls"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _case_str(c: Any) -> str:
    """Normalize a DivergenceCase (enum or raw string) to its value string."""
    return c.value if hasattr(c, "value") else str(c)


def _default_analyze(target: Any, compile: Any, class_id: int = 0):
    """Real default: calls analyze_iteration_full from mwcc_debug.convergence."""
    from src.mwcc_debug.convergence import analyze_iteration_full
    return analyze_iteration_full(target, compile, class_id=class_id)


def _default_classify(prev: Any, curr: Any, *, edit_was_order_change: bool,
                      history: list, checkdiff_clean: bool):
    """Real default: calls classify_progress from mwcc_debug.progress_classifier."""
    from src.mwcc_debug.progress_classifier import classify_progress
    return classify_progress(prev, curr,
                             edit_was_order_change=edit_was_order_change,
                             history=history,
                             checkdiff_clean=checkdiff_clean)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class DirectedScorePipeline:
    """Pure directed scorer that scores a candidate against its parent state.

    All injectable adapters default to the real implementations; tests supply
    fakes so no mwcc compilation occurs.

    Args:
        analyze:               (target, compile, class_id) -> (state, report, reanchor)
        compile_from_text:     (art) -> Compile  [or None → built inside score_directed]
        decisions_of:          (compile) -> {ig_idx: ColorgraphDecision}
        classify:              classify_progress signature
        coverage_floor:        minimum fraction of roles that must reanchor for validity
        plateau_n:             window size for should_escalate plateau detection
        parent_displacement_of: (parent_state) -> float; extracts the parent's displacement
    """

    def __init__(
        self,
        *,
        analyze: Optional[Callable] = None,
        compile_from_text: Optional[Callable] = None,
        decisions_of: Optional[Callable] = None,
        classify: Optional[Callable] = None,
        coverage_floor: float = 0.5,
        plateau_n: int = 3,
        parent_displacement_of: Callable = lambda ps: getattr(ps, "displacement", 0.0),
    ) -> None:
        self._analyze = analyze if analyze is not None else _default_analyze
        self._compile_from_text = compile_from_text  # None = build inside score_directed
        self._decisions_of = decisions_of  # None = build inside score_directed
        self._classify = classify if classify is not None else _default_classify
        self._coverage_floor = coverage_floor
        self._plateau_n = plateau_n
        self._parent_displacement_of = parent_displacement_of

    # ------------------------------------------------------------------
    # score_directed
    # ------------------------------------------------------------------

    def score_directed(self, art: Any, call: DirectedScoringCall) -> Any:
        """Score *art* against *call.parent_state*, returning a new CandidateArtifact.

        Pure: does not mutate art, call, call.parent_state, or any global state.
        All metadata is assembled into a fresh DirectedMeta and a new artifact
        is returned via dataclasses.replace.
        """
        obj = call.objective
        parent_state = call.parent_state

        # --- validity gate 1: roles ---
        roles = obj.role_target.roles
        if not roles:
            return self._invalid(art, call, "no_roles")

        # --- compile and analyze ---
        if self._compile_from_text is not None:
            compile = self._compile_from_text(art)
        else:
            # Real default: build Compile from pcdump text + source blob.
            from src.mwcc_debug.role_descriptor import Compile
            pcdump_text = art.pcdump_path.read_text(encoding="utf-8")
            source_text = art.source_blob.read_text(encoding="utf-8")
            compile = Compile.from_text(pcdump_text, obj.role_target.function, source_text)

        state, report, reanchor = self._analyze(
            obj.role_target, compile, class_id=obj.class_id
        )

        # --- validity gates 2-4: case, report, coverage ---
        case = _case_str(state.fact.case)
        if case == "none":
            return self._invalid(art, call, "case_none")
        if case == "abstained":
            return self._invalid(art, call, "case_abstained")
        if report is None:
            return self._invalid(art, call, "no_report")

        n_roles = max(len(roles), 1)
        if len(reanchor.matched) / n_roles < self._coverage_floor:
            return self._invalid(art, call, "low_coverage")

        # --- compute decisions ---
        if self._decisions_of is not None:
            decisions = self._decisions_of(compile)
        else:
            # Real default: extract from colorgraph sections for class_id.
            from src.mwcc_debug.colorgraph_parser import find_function
            fe = find_function(compile.fev, obj.role_target.function)
            if fe and fe.colorgraph_sections:
                matching = [s for s in fe.colorgraph_sections if s.class_id == obj.class_id]
                section = matching[-1] if matching else fe.colorgraph_sections[-1]
                decisions = {d.ig_idx: d for d in section.decisions}
            else:
                decisions = {}

        # --- metrics ---
        cand = candidate_iter_by_original_ig(reanchor.matched, decisions)
        od = order_distance(cand, obj.objective_iter_by_original_ig)
        disp = displacement(cand, obj.objective_iter_by_original_ig)

        # --- classify progress ---
        eoc = parent_state.last_lever in ORDER_CHANGE_MUTATORS
        label = self._classify(
            parent_state.prev_state,
            state,
            edit_was_order_change=eoc,
            history=list(parent_state.history),
            checkdiff_clean=False,
        ).value

        # --- displacement delta vs parent ---
        parent_disp = self._parent_displacement_of(parent_state)
        delta = disp - parent_disp

        # --- assemble meta (all fields populated) ---
        parent_id = (
            getattr(call.parent_state.current_best, "candidate_id", None)
            if call.parent_state.current_best is not None
            else None
        )
        meta = DirectedMeta(
            candidate_id=art.candidate_id,
            source_hash=art.source_hash,
            iteration=0,
            parent_id=parent_id,
            parent_state_id=parent_state.state_id,
            valid=True,
            invalid_reason=None,
            case=case,
            label=label,
            order_distance=od,
            displacement=disp,
            displacement_delta=delta,
            reanchor_matched=len(reanchor.matched),
            reanchor_total=len(roles),
            diagnosis_chars=len(case),
            applied_mutator=parent_state.last_lever,
            directed_scalar=disp,
        )

        return replace(art, directed_score=disp, directed_meta=meta, status="ok")

    # ------------------------------------------------------------------
    # _invalid
    # ------------------------------------------------------------------

    def _invalid(self, art: Any, call: DirectedScoringCall, reason: str) -> Any:
        """Return art with a DirectedMeta marking the candidate as invalid."""
        parent_state = call.parent_state
        meta = DirectedMeta(
            candidate_id=art.candidate_id,
            source_hash=art.source_hash,
            iteration=0,
            parent_id=None,
            parent_state_id=parent_state.state_id,
            valid=False,
            invalid_reason=reason,
            case=None,
            label=None,
            order_distance=0,
            displacement=0.0,
            displacement_delta=0.0,
            reanchor_matched=0,
            reanchor_total=0,
            diagnosis_chars=0,
            applied_mutator=parent_state.last_lever,
            directed_scalar=0.0,
        )
        return replace(art, directed_meta=meta, status="invalid")

    # ------------------------------------------------------------------
    # should_escalate
    # ------------------------------------------------------------------

    def should_escalate(self, art: Any, ctx: Any) -> bool:
        """Return True if the search has plateaued and should escalate.

        Plateau definition: the value *plateau_n* steps ago is <= the minimum
        of the last *plateau_n* values — i.e. no value in the window beat the
        starting value of that window, so there's been no improvement.

        Corrected formula: h[-plateau_n] == min(h[-plateau_n:])
          - [5,5,5]: h[-3]=5, min([5,5,5])=5 → True (flat)
          - [7,6,5]: h[-3]=7, min([7,6,5])=5 → False (improving)
          - [5,5]:   len < plateau_n → False
        """
        h = ctx.byte_history
        n = self._plateau_n
        if len(h) < n:
            return False
        return h[-n] == min(h[-n:])
