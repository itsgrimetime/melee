from src.search.directed.metric import (
    candidate_iter_by_original_ig,
    order_distance,
    displacement,
    phys_assignment_buckets,
    phys_match_fraction,
    phys_mismatch_count,
)


class _Dec:
    def __init__(self, iter_idx, assigned_reg=None):
        self.iter_idx = iter_idx
        self.assigned_reg = assigned_reg


def test_reanchor_mapping():
    # matched = {new_ig: original_ig}; decisions keyed by new_ig -> iter positions per original_ig
    assert candidate_iter_by_original_ig({1: 37, 2: 34}, {1: _Dec(103), 2: _Dec(3)}) == {37: 103, 34: 3}


def test_reanchor_mapping_skips_missing_decision():
    assert candidate_iter_by_original_ig({1: 37, 2: 34}, {1: _Dec(103)}) == {37: 103}


def test_order_distance_binary_for_two_roles():
    objective = {37: 3, 34: 103}                 # objective: ig37 earlier than ig34
    assert order_distance({37: 103, 34: 3}, objective) == 1   # candidate flipped -> 1 inversion
    assert order_distance({37: 3, 34: 103}, objective) == 0   # candidate matches objective -> 0


def test_order_distance_ignores_unmapped():
    assert order_distance({37: 3}, {37: 3, 34: 103}) == 0     # only one role present -> no pairs


def test_displacement_measures_pre_flip_movement():
    objective = {37: 3, 34: 103}                 # want ig37 earlier (objective signed gap 37-34 = -100)
    far  = displacement({37: 103, 34: 3},  objective)   # fully inverted (gap +100)
    near = displacement({37: 60,  34: 50}, objective)   # STILL wrong order (gap +10) but iters closer
    assert near > far                            # raw-position metric rises as the pair approaches objective
    exact = displacement({37: 3, 34: 103}, objective)
    assert exact >= near                         # objective order scores highest


def test_displacement_degenerate_single_role():
    assert displacement({37: 3}, {37: 3, 34: 103}) == 0.0


# --- phys-match (the GATE signal — Codex round 4 "Fix A") ---

def test_phys_match_buckets_satisfied_blocked_abstained():
    proof = {37: 27, 34: 29, 99: 5}              # 99 will not reanchor -> abstained
    matched = {1: 37, 2: 34}                       # new_ig -> original_ig
    decisions = {1: _Dec(10, assigned_reg=27),     # 37 -> 27 == desired -> satisfied
                 2: _Dec(20, assigned_reg=27)}     # 34 -> 27 != 29     -> blocked
    b = phys_assignment_buckets(proof, matched, decisions)
    assert [r["original_ig"] for r in b["satisfied"]] == [37]
    assert [r["original_ig"] for r in b["blocked"]] == [34]
    assert [r["original_ig"] for r in b["abstained"]] == [99]


def test_phys_match_fraction_and_mismatch_count():
    # The 9ACC wall: 0/2 by construction (neither role at desired phys).
    proof = {37: 27, 34: 29}
    matched = {1: 37, 2: 34}
    wall = {1: _Dec(0, assigned_reg=29), 2: _Dec(0, assigned_reg=27)}   # swapped
    b = phys_assignment_buckets(proof, matched, wall)
    assert phys_match_fraction(b, len(proof)) == 0.0
    assert phys_mismatch_count(b) == 2

    win = {1: _Dec(0, assigned_reg=27), 2: _Dec(0, assigned_reg=29)}     # both right
    b2 = phys_assignment_buckets(proof, matched, win)
    assert phys_match_fraction(b2, len(proof)) == 1.0
    assert phys_mismatch_count(b2) == 0          # 0 == the phys-swap win


def test_phys_match_empty_proof_is_zero():
    b = phys_assignment_buckets({}, {1: 37}, {1: _Dec(0, assigned_reg=27)})
    assert phys_match_fraction(b, 0) == 0.0
    assert phys_mismatch_count(b) == 0
