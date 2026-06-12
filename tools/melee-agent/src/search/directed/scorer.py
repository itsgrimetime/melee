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
    phys_assignment_buckets,
    phys_match_fraction,
    phys_mismatch_count,
)
from src.search.directed.order_metric import score_candidate_reanchored


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


def _checkdiff_gate_for_byte_score(byte_score: int | None) -> str:
    if byte_score is None:
        return "unknown"
    return "byte_match" if byte_score == 0 else "byte_mismatch"


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
        byte_scorer: Optional[Any] = None,
        directed_from_start: bool = False,
    ) -> None:
        self._analyze = analyze if analyze is not None else _default_analyze
        self._compile_from_text = compile_from_text  # None = build inside score_directed
        self._decisions_of = decisions_of  # None = build inside score_directed
        self._classify = classify if classify is not None else _default_classify
        self._coverage_floor = coverage_floor
        self._plateau_n = plateau_n
        self._parent_displacement_of = parent_displacement_of
        # Byte scorer for score_byte(). If None, score_byte passes through.
        self._byte_scorer = byte_scorer
        # directed_from_start: an explicit, documented config for a
        # directed-ONLY run that scores directed from iteration 1 by design
        # (Codex round 4 P1).  Replaces the old `_AlwaysEscalate` subclass hack
        # in run.py.  When False, the byte-plateau heuristic governs escalation
        # for mixed tier-1/tier-2 runs.
        self._directed_from_start = directed_from_start

    # ------------------------------------------------------------------
    # score_byte
    # ------------------------------------------------------------------

    def score_byte(self, art: Any, target: Any) -> Any:
        """Tier-1 byte-distance score.  Delegates to the real byte scorer.

        This is required by the scheduler's directed-mode branch (which calls
        ``directed.score_pipeline.score_byte`` for every compiled candidate
        before escalating to ``score_directed``).  The default implementation
        uses ``RealByteScorer``; callers may inject a custom scorer via
        ``DirectedScorePipeline(byte_scorer=...)``.
        """
        from dataclasses import replace as _replace
        if self._byte_scorer is None:
            # No byte scorer injected — just pass through (score = None)
            return art
        if art.object_path is None:
            return _replace(art, status="score_failed")
        dist = self._byte_scorer.byte_distance(art.object_path, target)
        return _replace(art, byte_score=dist, status="ok")

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

        # --- ORDER-MODE BRANCH (order-distance directed search, T4) ----------
        # Placed BEFORE the compile/analyze/case/report/coverage machinery (B3):
        # in order mode the §3.3 rules (1.0 target-role reanchor coverage, >= 2
        # anchored — enforced inside the shared scoring core) are THE validity
        # gate; the divergence-case analysis and the generic coverage_floor=0.5
        # are phys-mode-only. Gate/scheduler polarity is untouched (Plan C).
        if getattr(obj, "objective_mode", "phys") == "order":
            return self._score_order(art, call)

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
            decisions = self._decisions_for_compile(compile, obj)
            fallback = self._force_phys_assignment_fallback(
                art,
                call,
                reanchor=reanchor,
                decisions=decisions,
            )
            if fallback is not None:
                return fallback
            return self._invalid(art, call, "case_abstained")
        if report is None:
            return self._invalid(art, call, "no_report")

        n_roles = max(len(roles), 1)
        if len(reanchor.matched) / n_roles < self._coverage_floor:
            return self._invalid(art, call, "low_coverage")

        # --- compute decisions ---
        decisions = self._decisions_for_compile(compile, obj)

        # --- GATE SIGNAL: phys-match (Codex round 4 "Fix A") -------------
        # Measure progress toward the desired PHYSICAL register assignment
        # (proof_force_phys / desired_phys vs the candidate's assigned_reg,
        # mapped through reanchor.matched).  The baseline IS the wall (9ACC
        # scores 0/N by construction), so a no-op that merely reproduces the
        # baseline coloring can NEVER inflate this signal.
        proof = getattr(obj, "proof_force_phys", None) or {}
        buckets = phys_assignment_buckets(proof, reanchor.matched, decisions)
        total_roles = len(proof) if proof else len(roles)
        disp = phys_match_fraction(buckets, total_roles)   # |satisfied|/total
        od = phys_mismatch_count(buckets)                  # 0 == the swap win

        # --- DIAGNOSTIC ONLY: the OLD iter-ordering metric --------------
        # Demoted to telemetry (Codex round 4); NEVER the gate signal.
        cand = candidate_iter_by_original_ig(reanchor.matched, decisions)
        iter_od = order_distance(cand, obj.objective_iter_by_original_ig)
        iter_disp = displacement(cand, obj.objective_iter_by_original_ig)

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
        applied_mutator, non_actionable = self._attribution(art, parent_state)

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
            # GATE SIGNAL: phys-match
            order_distance=od,
            displacement=disp,
            displacement_delta=delta,
            reanchor_matched=len(reanchor.matched),
            reanchor_total=len(roles),
            diagnosis_chars=len(case),
            applied_mutator=applied_mutator,
            directed_scalar=disp,
            proof_assignments=buckets,
            byte_score=art.byte_score,
            checkdiff_gate=_checkdiff_gate_for_byte_score(art.byte_score),
            non_actionable=non_actionable,
            # DIAGNOSTIC ONLY: the old iter-ordering metric
            iter_order_distance=iter_od,
            iter_displacement=iter_disp,
        )

        return replace(art, directed_score=disp, directed_meta=meta, status="ok")

    # ------------------------------------------------------------------
    # _score_order — the objective_mode == "order" scoring path.
    # ------------------------------------------------------------------

    def _score_order(self, art: Any, call: DirectedScoringCall) -> Any:
        """Score a candidate against the PROVEN order vector via the shared
        generalized scorer (T5).  Lower order_distance is better; the §3.3
        validity rule (inside the core) rejects candidates that lose a target
        role.

        Field semantics in order mode (B6):
          * order_distance   = role-matched Kendall vs the proven vector;
          * displacement     = metric.displacement — the spec's smooth SIGNED-
                               GAP diagnostic over the same role positions
                               (never the accept/win signal; never a phys
                               fraction);
          * directed_scalar  = the Kendall scalar (float).
        Phys telemetry is NOT folded into any gate field; the CandidateScore
        retains phys_matched for diagnostics read directly by the kill switch.

        Polarity note: the gate and scheduler still read displacement fields
        higher-is-better; flipping that comparator is Plan C (T8/T9). For A+B
        the kill switch reads CandidateScore.order_distance directly, so the
        scorer exposing the objective is sufficient.
        """
        from src.search.directed.metric import displacement as signed_gap_displacement

        obj = call.objective
        parent_state = call.parent_state
        order_target = dict(obj.objective_iter_by_original_ig)
        phys_target = dict(obj.proof_force_phys)
        pcdump_text = art.pcdump_path.read_text(encoding="utf-8")
        source_text = art.source_blob.read_text(encoding="utf-8")
        ref_descs = self._order_ref_descs(obj)

        cs = score_candidate_reanchored(
            pcdump_text, ref_descs, function=obj.role_target.function,
            class_id=obj.class_id, order_target=order_target,
            phys_target=phys_target, cand_source=source_text,
        )
        if not cs.valid:
            return self._invalid(art, call, cs.invalid_reason or "target_role_lost")

        # B6: displacement carries the SIGNED-GAP DIAGNOSTIC.
        disp = signed_gap_displacement(cs.ranks_by_role or {}, order_target)
        parent_disp = self._parent_displacement_of(parent_state)
        applied_mutator, non_actionable = self._attribution(art, parent_state)
        parent_id = (
            getattr(call.parent_state.current_best, "candidate_id", None)
            if call.parent_state.current_best is not None else None
        )
        meta = DirectedMeta(
            candidate_id=art.candidate_id,
            source_hash=art.source_hash,
            iteration=0,
            parent_id=parent_id,
            parent_state_id=parent_state.state_id,
            valid=True,
            invalid_reason=None,
            case="order",
            label="order",
            order_distance=cs.order_distance,
            displacement=disp,
            displacement_delta=disp - parent_disp,
            reanchor_matched=len(cs.ranks_by_role or {}),
            reanchor_total=len(order_target),
            diagnosis_chars=len("order"),
            applied_mutator=applied_mutator,
            directed_scalar=float(cs.order_distance),
            proof_assignments=None,
            byte_score=art.byte_score,
            checkdiff_gate=_checkdiff_gate_for_byte_score(art.byte_score),
            non_actionable=non_actionable,
            iter_order_distance=cs.order_distance,
            iter_displacement=disp,
        )
        return replace(art, directed_score=float(cs.order_distance),
                       directed_meta=meta, status="ok")

    def _order_ref_descs(self, obj: Any) -> dict:
        """Build the baseline identity reference descriptors for order scoring.

        Prefer the objective's pre-built baseline_compile; fall back to building
        from the baseline pcdump path.  One build per candidate is dwarfed by
        the candidate compile, so no caching."""
        from src.mwcc_debug.role_descriptor import Compile, build_descriptors
        bc = obj.baseline_compile
        if bc is not None:
            return build_descriptors(bc, class_id=obj.class_id)
        if obj.baseline_pcdump_path is not None:
            from pathlib import Path
            text = Path(obj.baseline_pcdump_path).read_text(encoding="utf-8")
            compile = Compile.from_text(text, obj.role_target.function, "")
            return build_descriptors(compile, class_id=obj.class_id)
        return {}

    # ------------------------------------------------------------------
    # _attribution — resolve applied_mutator + the non_actionable flag.
    # ------------------------------------------------------------------

    def _attribution(self, art: Any, parent_state: Any) -> tuple:
        """Return ``(applied_mutator, non_actionable)``.

        Prefer mutator attribution from ``art.provenance.mutation`` (set by
        DirectedSource with the exact key returned from propose); fall back to
        ``parent_state.last_lever``.  Strip the ``@N`` dedup suffix from pair-
        enumeration keys.

        ``non_actionable`` is True when the provenance carries the
        ``non_actionable`` marker — i.e. the mutator came from the blind
        ``var_name=None`` decl-pair fallback with NO causal link to the
        diagnosis (Codex round 4 P0 attribution integrity).  The gate treats
        such a candidate as UNATTRIBUTED.
        """
        prov = getattr(art, "provenance", None)
        prov_mutation = getattr(prov, "mutation", None)
        if prov_mutation is not None and "@" in str(prov_mutation):
            prov_mutation = str(prov_mutation).split("@")[0]
        applied_mutator = prov_mutation or parent_state.last_lever
        non_actionable = False
        meta = getattr(prov, "producer_meta", None)
        if isinstance(meta, dict) and meta.get("non_actionable"):
            non_actionable = True
        return applied_mutator, non_actionable

    def _decisions_for_compile(self, compile: Any, obj: Any) -> dict:
        if self._decisions_of is not None:
            return self._decisions_of(compile)

        from src.mwcc_debug.colorgraph_parser import find_function

        fev_arg = [compile.fev] if not isinstance(compile.fev, list) else compile.fev
        fe = find_function(fev_arg, obj.role_target.function)
        if fe and fe.colorgraph_sections:
            matching = [
                s for s in fe.colorgraph_sections
                if s.class_id == obj.class_id
            ]
            section = matching[-1] if matching else fe.colorgraph_sections[-1]
            return {d.ig_idx: d for d in section.decisions}
        return {}

    def _force_phys_assignment_fallback(
        self,
        art: Any,
        call: DirectedScoringCall,
        *,
        reanchor: Any,
        decisions: dict,
    ) -> Any | None:
        obj = call.objective
        proof = getattr(obj, "proof_force_phys", None) or {}
        if not proof:
            return None

        matched = getattr(reanchor, "matched", None) or {}
        # Reuse the shared phys-match helper so the abstained fallback and the
        # main score_directed path compute the SAME gate signal.
        buckets = phys_assignment_buckets(proof, matched, decisions)
        satisfied = buckets["satisfied"]
        blocked = buckets["blocked"]
        abstained = buckets["abstained"]

        total = len(proof)
        score = phys_match_fraction(buckets, total)
        parent_state = call.parent_state
        parent_disp = self._parent_displacement_of(parent_state)
        applied_mutator, non_actionable = self._attribution(art, parent_state)
        if applied_mutator is None:
            applied_mutator = "force_phys_assignment"

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
            case="force_phys_assignment",
            label="assignment_fallback",
            order_distance=len(blocked) + len(abstained),
            displacement=score,
            displacement_delta=score - parent_disp,
            reanchor_matched=len(satisfied) + len(blocked),
            reanchor_total=len(proof),
            diagnosis_chars=len("force_phys_assignment"),
            applied_mutator=applied_mutator,
            directed_scalar=score,
            proof_assignments={
                "satisfied": satisfied,
                "blocked": blocked,
                "abstained": abstained,
            },
            byte_score=art.byte_score,
            checkdiff_gate=_checkdiff_gate_for_byte_score(art.byte_score),
            non_actionable=non_actionable,
        )
        return replace(
            art,
            directed_score=score,
            directed_meta=meta,
            status="ok",
        )

    # ------------------------------------------------------------------
    # _invalid
    # ------------------------------------------------------------------

    def _invalid(self, art: Any, call: DirectedScoringCall, reason: str) -> Any:
        """Return art with a DirectedMeta marking the candidate as invalid."""
        parent_state = call.parent_state
        parent_id = (
            getattr(call.parent_state.current_best, "candidate_id", None)
            if call.parent_state.current_best is not None
            else None
        )
        applied_mutator, non_actionable = self._attribution(art, parent_state)
        meta = DirectedMeta(
            candidate_id=art.candidate_id,
            source_hash=art.source_hash,
            iteration=0,
            parent_id=parent_id,
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
            applied_mutator=applied_mutator,
            directed_scalar=0.0,
            byte_score=art.byte_score,
            checkdiff_gate=_checkdiff_gate_for_byte_score(art.byte_score),
            non_actionable=non_actionable,
        )
        return replace(art, directed_meta=meta, status="invalid")

    # ------------------------------------------------------------------
    # should_escalate
    # ------------------------------------------------------------------

    def should_escalate(self, art: Any, ctx: Any) -> bool:
        """Return True if directed scoring should run for this batch.

        When ``directed_from_start`` is set (a directed-only run), this is
        unconditionally True from iteration 1 — directed scoring IS the run's
        purpose.  This is the explicit, documented replacement for the old
        ``_AlwaysEscalate`` subclass.

        Otherwise the byte-plateau heuristic governs (mixed tier-1/tier-2):
        the value *plateau_n* steps ago is <= the minimum of the last
        *plateau_n* values — i.e. no value in the window beat the starting
        value of that window, so there's been no improvement.

        Corrected formula: h[-plateau_n] == min(h[-plateau_n:])
          - [5,5,5]: h[-3]=5, min([5,5,5])=5 → True (flat)
          - [7,6,5]: h[-3]=7, min([7,6,5])=5 → False (improving)
          - [5,5]:   len < plateau_n → False
        """
        if self._directed_from_start:
            return True
        h = ctx.byte_history
        n = self._plateau_n
        if len(h) < n:
            return False
        return h[-n] == min(h[-n:])
