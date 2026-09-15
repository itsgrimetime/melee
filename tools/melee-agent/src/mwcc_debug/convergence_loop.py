"""Convergence loop driver: orchestrates analyze -> classify -> (agent edits) -> repeat.

run_convergence_loop(function, target, editor, checker, ...) -> LoopResult
"""
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Optional, Protocol
from .first_divergence import DivergenceCase
from .progress_classifier import ProgressLabel, IterationState, classify_progress

_NONPROGRESS = {ProgressLabel.SAME, ProgressLabel.NON_COMPARABLE, ProgressLabel.ROLE_GONE}
_RANK_PROGRESS = {ProgressLabel.MOVED_LATER, ProgressLabel.NEW_EARLIER}
_ORDER_CASES = {DivergenceCase.C_DISPENSE_ORDER, DivergenceCase.C2_STICKY_POOL}


class Outcome(enum.Enum):
    CONVERGED = "converged"
    TARGET_SATISFIED = "target_satisfied"
    PROXY_SATISFIED = "proxy_satisfied"
    CYCLE = "cycle"
    STALLED = "stalled"
    BUDGET = "budget"
    UNANALYZABLE = "unanalyzable"
    NO_EDIT = "no_edit"


@dataclass(frozen=True)
class IterationContext:
    function: str
    target: object                      # TargetSpec
    compile: object                     # Compile
    report: object                      # FirstDivergenceReport | None
    state: IterationState
    history: tuple
    iteration: int


@dataclass(frozen=True)
class EditProposal:
    new_compile: object                 # Compile
    predicted_lever: DivergenceCase
    rationale: str = ""
    obj_path: Optional[object] = None  # Path to the recompiled .o; None if editor didn't produce one


@dataclass(frozen=True)
class IterationRecord:
    iteration: int
    label: ProgressLabel
    case: DivergenceCase
    identity: Optional[int]
    role_order_rank: Optional[int]
    diverging_identity_confident: bool
    non_comparable_reason: Optional[str]
    predicted_lever: Optional[DivergenceCase]
    edit_was_order_change: bool
    checkdiff_clean: bool
    reanchor_matched: int
    reanchor_total: int
    gone_roles: tuple
    rationale: str
    editor_meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LoopResult:
    outcome: Outcome
    iterations: tuple
    cause_report: tuple


class Editor(Protocol):
    def edit(self, ctx: IterationContext) -> Optional[EditProposal]: ...

class Checker(Protocol):
    def is_clean(self, obj_path) -> bool: ...   # checkdiff verdict on the recompiled .o


def _stalled(records, k: int) -> bool:
    if len(records) < k:
        return False
    window = records[-k:]
    if any(r.label in _RANK_PROGRESS for r in window):
        return False
    return all(r.label in _NONPROGRESS for r in window)


def _non_comparable_reason(edit_was_order_change, identity, curr_rank, prev_rank) -> str:
    if edit_was_order_change:
        return "order_change"
    if identity is None or curr_rank is None or prev_rank is None:
        return "no_identity_or_rank"
    return "same_rank_diff_case"


def _cause_report(outcome: Outcome, records, target) -> tuple:
    causes = []
    if not records:
        return ()
    matched = [r.reanchor_matched for r in records]
    total = records[-1].reanchor_total or 1
    if any(r.label == ProgressLabel.ROLE_GONE for r in records) or \
       min(matched) < 0.5 * total or \
       any(r.non_comparable_reason == "no_identity_or_rank" for r in records):
        causes.append("identity instability: low/unstable reanchor coverage or unidentified divergence")
    if all(r.diverging_identity_confident for r in records) and \
       not any(r.label == ProgressLabel.MOVED_LATER for r in records):
        causes.append("edit quality: identity stable but no MOVED_LATER progress")
    if outcome in (Outcome.PROXY_SATISFIED, Outcome.TARGET_SATISFIED):
        causes.append(f"partial/proxy target (coverage={getattr(target, 'target_coverage', '?')})")
    if outcome == Outcome.CYCLE and records[-1].diverging_identity_confident and \
       not any(r.non_comparable_reason == "no_identity_or_rank" for r in records):
        causes.append("possible mutual-exclusivity: stable identity re-diverges regardless of edits")
    return tuple(sorted(set(causes)))


def _make_converged_record(it: int, last_lever, last_state: Optional[IterationState]) -> IterationRecord:
    """Build the IterationRecord for the converged (ASM_MATCHED) iteration."""
    case = last_state.fact.case if last_state is not None else DivergenceCase.NONE
    identity = last_state.identity if last_state is not None else None
    rank = last_state.role_order_rank if last_state is not None else None
    return IterationRecord(
        iteration=it, label=ProgressLabel.ASM_MATCHED, case=case,
        identity=identity, role_order_rank=rank,
        diverging_identity_confident=identity is not None,
        non_comparable_reason=None, predicted_lever=last_lever,
        edit_was_order_change=last_lever in _ORDER_CASES if last_lever is not None else False,
        checkdiff_clean=True, reanchor_matched=0, reanchor_total=0,
        gone_roles=(), rationale="")


def run_convergence_loop(function, target, editor: Editor, checker: Checker, *,
                         iteration_cap: int, class_id: int = 0, stall_k: int = 3,
                         analyze_fn=None, wall_clock=None,
                         baseline_compile=None, baseline_obj=None) -> LoopResult:
    if analyze_fn is None:
        from .convergence import analyze_iteration_full
        analyze_fn = analyze_iteration_full

    compile = baseline_compile if baseline_compile is not None else getattr(target, "baseline_compile", None)
    current_obj = baseline_obj
    history, records = [], []
    prev_state, last_lever = None, None

    def finish(outcome):
        # CONVERGED is a clean win -> no candidate causes (spec §5/§6); only
        # non-converged terminals carry a cause report.
        causes = () if outcome == Outcome.CONVERGED else _cause_report(outcome, records, target)
        return LoopResult(outcome=outcome, iterations=tuple(records), cause_report=causes)

    for it in range(iteration_cap):
        assert (prev_state is None) == (last_lever is None)   # invariant (spec §5)
        if wall_clock is not None and wall_clock.expired():
            return finish(Outcome.BUDGET)
        # (a) win check first — never edit past a win
        if checker.is_clean(current_obj):
            records.append(_make_converged_record(it, last_lever, prev_state))
            return finish(Outcome.CONVERGED)
        # (b) analyze
        try:
            state, report, res = analyze_fn(target, compile, class_id)
        except ValueError:
            return finish(Outcome.UNANALYZABLE)
        matched, total = len(res.matched), len(target.roles)
        order_change = last_lever in _ORDER_CASES
        # (c) classify
        label = classify_progress(prev_state, state, edit_was_order_change=order_change,
                                  history=history, checkdiff_clean=False)
        ncr = (_non_comparable_reason(order_change, state.identity, state.role_order_rank,
                                      prev_state.role_order_rank if prev_state else None)
               if label == ProgressLabel.NON_COMPARABLE else None)
        records.append(IterationRecord(
            iteration=it, label=label, case=state.fact.case, identity=state.identity,
            role_order_rank=state.role_order_rank,
            diverging_identity_confident=state.identity is not None,
            non_comparable_reason=ncr, predicted_lever=last_lever,
            edit_was_order_change=order_change, checkdiff_clean=False,
            reanchor_matched=matched, reanchor_total=total,
            gone_roles=tuple(sorted(state.gone_roles)), rationale=""))
        # (d) terminal labels + guards
        if state.fact.case == DivergenceCase.ABSTAINED:
            return finish(Outcome.UNANALYZABLE)
        if state.fact.case == DivergenceCase.NONE and matched == 0:
            return finish(Outcome.UNANALYZABLE)
        if label == ProgressLabel.TARGET_SATISFIED:
            real = target.target_kind == "matched_natural" or target.causal_closure
            return finish(Outcome.TARGET_SATISFIED if real else Outcome.PROXY_SATISFIED)
        if label == ProgressLabel.CYCLE:
            return finish(Outcome.CYCLE)
        if _stalled(records, stall_k):
            return finish(Outcome.STALLED)
        # (e) edit
        proposal = editor.edit(IterationContext(function, target, compile, report, state,
                                                tuple(history), it))
        if proposal is None:
            return finish(Outcome.NO_EDIT)
        history.append((state.identity, state.fact.case))
        prev_state, compile, last_lever = state, proposal.new_compile, proposal.predicted_lever
        current_obj = proposal.obj_path
    return finish(Outcome.BUDGET)
