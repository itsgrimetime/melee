"""Convergence orchestration: reanchor -> first-divergence -> IterationState.

analyze_iteration(target, new_compile, class_id) is the single step the loop
driver calls each iteration to build an IterationState it can hand to
classify_progress.
"""
from __future__ import annotations
from . import role_reanchor as rr
from . import first_divergence as fd
from .progress_classifier import IterationState, FactView

# Non-MATCHED matcher statuses meaning a tracked role can no longer be confidently
# followed (-> ROLE_GONE / CYCLE signals for the loop). "no_desired_phys" is
# deliberately excluded: it is a ref-superset-of-desired seam, not a destabilization.
_GONE_STATUSES = {"gone", "merged", "split", "ambiguous", "non_comparable",
                  "unstable_identity", "no_descriptor"}


def analyze_iteration_full(target, new_compile, class_id: int = 0):
    """(state, report, reanchor_result). report is None when reanchor yields an
    empty force-phys map (nothing to analyze — caller distinguishes identity
    collapse from genuine satisfaction via reanchor_result.matched)."""
    res = rr.reanchor(target, new_compile, class_id=class_id)
    gone = frozenset(ig for ig, status in res.diagnostics.items() if status in _GONE_STATUSES)
    rank_by_orig = {r.original_ig: r.role_order_rank for r in target.roles}
    if not res.force_phys:
        return (IterationState(fact=FactView(case=fd.DivergenceCase.NONE, ig_idx=-1),
                               identity=None, role_order_rank=None, gone_roles=gone),
                None, res)
    coloring = fd.TargetColoring(class_id=class_id, force_phys=res.force_phys)
    report = fd.analyze_first_divergence(new_compile.fev, coloring)
    fact = report.fact
    identity = res.matched.get(fact.ig_idx)
    rank = rank_by_orig.get(identity) if identity is not None else None
    return (IterationState(fact=FactView(case=fact.case, ig_idx=fact.ig_idx),
                           identity=identity, role_order_rank=rank, gone_roles=gone),
            report, res)


def analyze_iteration(target, new_compile, class_id: int = 0) -> IterationState:
    """Re-anchor `target` into `new_compile`, run first-divergence on the resulting
    force-phys map, and package the result as an IterationState. The diverging node
    (fact.ig_idx, in the new compile's numbering) is mapped back to its target-role
    identity via the reanchor matched pairs, and that role's role_order_rank is
    looked up from the target spec."""
    return analyze_iteration_full(target, new_compile, class_id)[0]
