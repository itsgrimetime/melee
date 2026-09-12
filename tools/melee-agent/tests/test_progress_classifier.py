from src.mwcc_debug import progress_classifier as pc
from src.mwcc_debug.first_divergence import DivergenceCase as DC


def _state(case=DC.B_TARGET_HIGHER, identity=10, rank=5, gone=()):
    """Minimal IterationState; `fact` only needs a `.case` for the classifier."""
    return pc.IterationState(fact=pc.FactView(case=case, ig_idx=99),
                             identity=identity, role_order_rank=rank,
                             gone_roles=frozenset(gone))


def _classify(prev, curr, order_change=False, history=None, checkdiff_clean=False):
    return pc.classify_progress(prev, curr, edit_was_order_change=order_change,
                                history=history or [], checkdiff_clean=checkdiff_clean)


def test_asm_matched_wins():
    assert _classify(_state(), _state(), checkdiff_clean=True) == pc.ProgressLabel.ASM_MATCHED

def test_target_satisfied_on_no_divergence():
    assert _classify(_state(), _state(case=DC.NONE)) == pc.ProgressLabel.TARGET_SATISFIED

def test_role_gone_when_tracked_role_vanishes():
    prev = _state(identity=10)
    curr = _state(identity=11, gone=(10,))            # role 10 (prev's) now gone
    assert _classify(prev, curr) == pc.ProgressLabel.ROLE_GONE

def test_cycle_when_state_revisited_before_prev():
    prev = _state(identity=11, case=DC.A_BLOCKED)
    curr = _state(identity=10, case=DC.B_TARGET_HIGHER)
    history = [(10, DC.B_TARGET_HIGHER), (11, DC.A_BLOCKED)]   # curr's key appeared 2 ago
    assert _classify(prev, curr, history=history) == pc.ProgressLabel.CYCLE

def test_non_comparable_on_order_change_edit():
    assert _classify(_state(rank=3), _state(rank=7),
                     order_change=True) == pc.ProgressLabel.NON_COMPARABLE

def test_non_comparable_without_confident_identity_or_rank():
    assert _classify(_state(), _state(identity=None)) == pc.ProgressLabel.NON_COMPARABLE
    assert _classify(_state(), _state(rank=None)) == pc.ProgressLabel.NON_COMPARABLE

def test_same_when_role_and_case_unchanged():
    assert _classify(_state(identity=10, case=DC.A_BLOCKED, rank=5),
                     _state(identity=10, case=DC.A_BLOCKED, rank=5)) == pc.ProgressLabel.SAME

def test_moved_later_when_diverging_rank_increases():
    assert _classify(_state(rank=3, identity=10), _state(rank=8, identity=20)) == pc.ProgressLabel.MOVED_LATER

def test_new_earlier_when_diverging_rank_decreases():
    assert _classify(_state(rank=8, identity=20), _state(rank=3, identity=10)) == pc.ProgressLabel.NEW_EARLIER


# ---------------------------------------------------------------------------
# Task 4: Gate-2 tests
# ---------------------------------------------------------------------------

def test_gate2_order_change_edit_is_non_comparable_even_if_rank_moved():
    """Spec Gate 2 + review #5: when the edit's lever was an order change (Case
    C/C2), rank is the edited dimension, so a rank move is NOT progress — it must
    be NON_COMPARABLE regardless of how rank shifted."""
    moved_later = _classify(_state(rank=2, identity=10), _state(rank=9, identity=20),
                            order_change=True)
    moved_earlier = _classify(_state(rank=9, identity=20), _state(rank=2, identity=10),
                              order_change=True)
    assert moved_later == pc.ProgressLabel.NON_COMPARABLE
    assert moved_earlier == pc.ProgressLabel.NON_COMPARABLE


def test_gate2_every_label_reachable():
    """Coverage: each ProgressLabel is produced by some classifier input, so the
    cascade has no dead branch."""
    seen = set()
    seen.add(_classify(_state(), _state(), checkdiff_clean=True))
    seen.add(_classify(_state(), _state(case=DC.NONE)))
    seen.add(_classify(_state(identity=10), _state(identity=11, gone=(10,))))
    seen.add(_classify(_state(identity=11, case=DC.A_BLOCKED),
                       _state(identity=10, case=DC.B_TARGET_HIGHER),
                       history=[(10, DC.B_TARGET_HIGHER), (11, DC.A_BLOCKED)]))
    seen.add(_classify(_state(), _state(), order_change=True))
    seen.add(_classify(_state(identity=10, case=DC.A_BLOCKED),
                       _state(identity=10, case=DC.A_BLOCKED)))
    seen.add(_classify(_state(rank=3, identity=10), _state(rank=8, identity=20)))
    seen.add(_classify(_state(rank=8, identity=20), _state(rank=3, identity=10)))
    assert seen == set(pc.ProgressLabel)
