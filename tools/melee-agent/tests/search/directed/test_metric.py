from src.search.directed.metric import candidate_iter_by_original_ig, order_distance, displacement


class _Dec:
    def __init__(self, iter_idx): self.iter_idx = iter_idx


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
