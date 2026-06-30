from src.mwcc_debug import role_matcher as rm
from src.mwcc_debug.role_descriptor import RoleDescriptor


def _desc(ig, sig="lwz r#, 0x2c(r#)", uses=(("lwz", 1),), param=False,
          var=None, conf=None, reg=10, lr=(0, 5), uc=1, spill=False):
    return RoleDescriptor(ig_idx=ig, first_def_sig=sig, use_site_multiset=tuple(uses),
                          is_param=param, var_name=var, var_confidence=conf,
                          assigned_reg=reg, live_range=lr, use_count=uc, spilled=spill)


def test_role_cost_identical_core_is_zero_despite_different_state():
    a = _desc(44, reg=10, lr=(0, 5))
    b = _desc(91, reg=31, lr=(8, 40))     # SAME core, DIFFERENT allocator state
    assert rm.role_cost(a, b) == 0.0      # state must not drive identity


def test_role_cost_different_first_def_is_costly():
    a = _desc(44, sig="lwz r#, 0x2c(r#)")
    b = _desc(91, sig="addi r#, r#, 1")
    assert rm.role_cost(a, b) > 0.5


def test_role_cost_matching_strong_var_lowers_cost():
    a = _desc(44, sig="addi r#, r#, 1", uses=(("stw", 2),), var="i", conf="best-guess")
    b = _desc(91, sig="li r#, 0", uses=(("add", 1),), var="i", conf="best-guess")
    c = _desc(92, sig="li r#, 0", uses=(("add", 1),), var="j", conf="best-guess")
    assert rm.role_cost(a, b) < rm.role_cost(a, c)   # same var name boosts


def test_min_cost_assignment_picks_global_optimum_not_greedy():
    # greedy-by-row would take (r0->c0 cost1), forcing r1->c1 cost9 (total 10);
    # optimum is r0->c1 (2) + r1->c0 (2) = 4.
    cost = {("r0", "c0"): 1.0, ("r0", "c1"): 2.0,
            ("r1", "c0"): 2.0, ("r1", "c1"): 9.0}
    out = rm.min_cost_assignment(["r0", "r1"], ["c0", "c1"], cost, unmatched_cost=5.0)
    assert out == {"r0": "c1", "r1": "c0"}

def test_min_cost_assignment_uses_unmatched_when_cheaper():
    cost = {("r0", "c0"): 1.0, ("r1", "c0"): 0.5}   # only one candidate, both want it
    out = rm.min_cost_assignment(["r0", "r1"], ["c0"], cost, unmatched_cost=3.0)
    # r1 takes c0 (0.5); r0 cheaper unmatched (3.0) than nothing-else -> None
    assert out == {"r1": "c0", "r0": None}


def test_match_roles_self_match_is_perfect_identity():
    descs = {44: _desc(44, sig="lwz r#, 0x10(r#)"),
             46: _desc(46, sig="addi r#, r#, 1", uses=(("stw", 1),))}
    out = rm.match_roles(descs, descs)
    assert out[44].status == rm.MatchStatus.MATCHED and out[44].new_ig == 44
    assert out[46].status == rm.MatchStatus.MATCHED and out[46].new_ig == 46

def test_match_roles_gone_when_no_candidate():
    ref = {44: _desc(44, sig="lwz r#, 0x10(r#)")}
    cand = {99: _desc(99, sig="fmadds f#, f#, f#, f#", uses=(("stfs", 3),))}
    out = rm.match_roles(ref, cand)
    assert out[44].status == rm.MatchStatus.GONE and out[44].new_ig is None

def test_match_roles_merged_when_two_refs_best_one_candidate():
    ref = {44: _desc(44, sig="li r#, 0"), 46: _desc(46, sig="li r#, 0")}  # indistinguishable
    cand = {70: _desc(70, sig="li r#, 0")}
    out = rm.match_roles(ref, cand)
    statuses = {out[44].status, out[46].status}
    assert rm.MatchStatus.MERGED in statuses


def test_match_roles_split_when_one_ref_matches_two_candidates_tightly():
    ref = {44: _desc(44, sig="add r#, r#, r#", uses=(("stw", 1),))}
    cand = {70: _desc(70, sig="add r#, r#, r#", uses=(("stw", 1),)),
            71: _desc(71, sig="add r#, r#, r#", uses=(("stw", 1),))}  # two equal matches
    out = rm.match_roles(ref, cand)
    assert out[44].status == rm.MatchStatus.SPLIT
    assert isinstance(out[44].new_ig, tuple) and set(out[44].new_ig) == {70, 71}

def test_match_roles_non_comparable_when_only_weak_collisions():
    ref = {44: _desc(44, sig="li r#, 0", uses=())}            # generic, no use sites
    cand = {70: _desc(70, sig="li r#, 0", uses=()),
            71: _desc(71, sig="li r#, 0", uses=())}
    out = rm.match_roles(ref, cand)
    assert out[44].status in (rm.MatchStatus.SPLIT, rm.MatchStatus.NON_COMPARABLE)


def test_match_roles_ambiguous_one_to_one_is_not_split():
    # 2 indistinguishable refs -> 2 indistinguishable candidates is an AMBIGUOUS
    # 1:1 renumbering, NOT a one->many split. Neither ref should be SPLIT.
    ref = {44: _desc(44, sig="add r#, r#, r#", uses=(("stw", 1),)),
           46: _desc(46, sig="add r#, r#, r#", uses=(("stw", 1),))}
    cand = {70: _desc(70, sig="add r#, r#, r#", uses=(("stw", 1),)),
            71: _desc(71, sig="add r#, r#, r#", uses=(("stw", 1),))}
    out = rm.match_roles(ref, cand)
    assert out[44].status != rm.MatchStatus.SPLIT
    assert out[46].status != rm.MatchStatus.SPLIT
    # each got a distinct candidate (clean 1:1), flagged AMBIGUOUS
    assert {out[44].new_ig, out[46].new_ig} == {70, 71}
    assert out[44].status == rm.MatchStatus.AMBIGUOUS
    assert out[46].status == rm.MatchStatus.AMBIGUOUS


def test_min_cost_assignment_large_n_with_ties_does_not_blow_up():
    # 30 rows/cols with a 10x10 all-zero tie block: the old branch-and-bound
    # exploded on the permutations. The min-cost-flow solver runs in polynomial
    # time and the self tie-break returns the identity instantly.
    import time
    rows = cols = list(range(30))
    cost = {(r, c): (0.0 if (r == c or (r < 10 and c < 10)) else 1.0)
            for r in rows for c in cols}
    t0 = time.time()
    out = rm.min_cost_assignment(rows, cols, cost, unmatched_cost=0.5)
    assert time.time() - t0 < 5.0           # must not blow up (was: hangs)
    assert all(out[r] == r for r in rows)    # self tie-break -> identity


def test_min_cost_assignment_exact_above_old_cap_not_greedy():
    # 18 rows (> the old greedy cap of 16) with a 2-row swap trap. Greedy by row
    # order takes r0->cA (1.0), then r1 cannot afford cB (9.0 >= unmatched) so it
    # falls to unmatched (5.0): total 6. The exact optimum swaps: r0->cB (2.0) +
    # r1->cA (1.0) = 3, rest identity. Proves large-N assignment stays EXACT, not
    # a silent greedy fallback (carry-forward #1 / Unit-3 prerequisite).
    rows = [f"r{i}" for i in range(18)]
    cols = ["cA", "cB"]
    cost = {("r0", "cA"): 1.0, ("r0", "cB"): 2.0,
            ("r1", "cA"): 1.0, ("r1", "cB"): 9.0}
    for i in range(2, 18):
        c = f"c{i}"
        cols.append(c)
        cost[(f"r{i}", c)] = 0.0
    out = rm.min_cost_assignment(rows, cols, cost, unmatched_cost=5.0)
    assert out["r0"] == "cB" and out["r1"] == "cA"
    assert all(out[f"r{i}"] == f"c{i}" for i in range(2, 18))


def test_match_roles_non_comparable_when_tied_candidates_are_weak():
    """>=2 uncontested tied candidates whose best cost is itself high (weak,
    non-distinctive signature: same generic first-def but differing use-sites +
    is_param) -> NON_COMPARABLE, not SPLIT. Pins the SPLIT/NON_COMPARABLE
    boundary (best_cost vs WEAK_SIG_CEILING)."""
    ref = {44: _desc(44, sig="li r#, 0", uses=(("x", 1),), param=True)}
    cand = {70: _desc(70, sig="li r#, 0", uses=(("y", 1),), param=False),
            71: _desc(71, sig="li r#, 0", uses=(("y", 1),), param=False)}
    out = rm.match_roles(ref, cand)
    assert out[44].status == rm.MatchStatus.NON_COMPARABLE      # best_cost 0.35 > 0.33
    assert isinstance(out[44].new_ig, tuple) and set(out[44].new_ig) == {70, 71}
