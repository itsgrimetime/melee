"""Progress classifier for the MWCC register-allocation directed-convergence loop.

classify_progress(prev, curr, ...) -> ProgressLabel labels how iteration-to-iteration
progress changed.  This is a PURE function over two consecutive IterationStates plus
context flags — gateable without a live loop.

Priority order in the cascade is deliberate; do not reorder:
  checkdiff -> NONE -> ROLE_GONE -> CYCLE -> order-change -> baseline(prev None)
  -> identity/rank gate -> SAME/MOVED_LATER/NEW_EARLIER
"""
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Optional
from .first_divergence import DivergenceCase


class ProgressLabel(enum.Enum):
    ASM_MATCHED = "asm_matched"
    TARGET_SATISFIED = "target_satisfied"
    MOVED_LATER = "moved_later"
    NEW_EARLIER = "new_earlier"
    NON_COMPARABLE = "non_comparable"
    SAME = "same"
    ROLE_GONE = "role_gone"
    CYCLE = "cycle"


@dataclass(frozen=True)
class FactView:
    """The slice of an AllocatorFact the classifier needs. analyze_iteration fills
    this from a real fact; tests construct it directly."""
    case: DivergenceCase
    ig_idx: int


@dataclass(frozen=True)
class IterationState:
    fact: FactView
    identity: Optional[int]            # diverging node's target-role id (original_ig), or None
    role_order_rank: Optional[int]     # that role's rank in the original target, or None
    gone_roles: frozenset = field(default_factory=frozenset)  # target roles now gone/unstable


def classify_progress(prev: Optional[IterationState], curr: IterationState, *,
                      edit_was_order_change: bool, history: list, checkdiff_clean: bool
                      ) -> ProgressLabel:
    """Label progress from `prev` to `curr`. `history` is the list of
    (identity, case) keys for every prior iteration INCLUDING prev (so history[-1]
    is prev's key). Priority order is deliberate — see inline rationale."""
    if checkdiff_clean:
        return ProgressLabel.ASM_MATCHED                 # the real win; check first
    if curr.fact.case == DivergenceCase.NONE:
        return ProgressLabel.TARGET_SATISFIED            # proxy caveat noted by caller (review #2)
    if prev is not None and prev.identity is not None and prev.identity in curr.gone_roles:
        return ProgressLabel.ROLE_GONE                   # a tracked target role vanished/destabilized
    key = (curr.identity, curr.fact.case)
    if key in history[:-1]:                              # revisited a state older than prev
        return ProgressLabel.CYCLE
    if edit_was_order_change:
        return ProgressLabel.NON_COMPARABLE              # rank is the edited dimension (Case C/C2)
    if prev is None:
        return ProgressLabel.SAME                        # baseline iteration; no movement yet
    if (curr.identity is None or curr.role_order_rank is None
            or prev.role_order_rank is None):
        return ProgressLabel.NON_COMPARABLE              # no confident identity/comparable rank (review #5)
    if curr.identity == prev.identity and curr.fact.case == prev.fact.case:
        return ProgressLabel.SAME
    if curr.role_order_rank > prev.role_order_rank:
        return ProgressLabel.MOVED_LATER                 # divergence moved to a later-ranked role
    if curr.role_order_rank < prev.role_order_rank:
        return ProgressLabel.NEW_EARLIER
    return ProgressLabel.NON_COMPARABLE                  # same rank, different case: undetermined
