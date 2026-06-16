from src.mwcc_debug import first_divergence as fd


def test_decision_view_reports_cap_hit():
    full = fd.DecisionView(ig_idx=5, iter_idx=0, assigned_reg=3,
                           n_interferers=2, interferers=((4, 9), (6, 10)), spilled=False)
    capped = fd.DecisionView(ig_idx=7, iter_idx=1, assigned_reg=4,
                             n_interferers=82, interferers=((4, 9),), spilled=False)
    assert fd.is_cap_hit(full) is False
    assert fd.is_cap_hit(capped) is True


def test_divergence_case_enum_values():
    assert fd.DivergenceCase.D_COALESCED.value == "D"
    assert fd.DivergenceCase.B_INVERSE.value == "B-inverse"


def test_select_class_section_picks_matching_class():
    from src.mwcc_debug.colorgraph_parser import parse_hook_events, find_function
    import pathlib
    fixtures = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"
    fpath = fixtures / "fn_802461BC_pcdump.txt"
    if not fpath.exists():
        import pytest
        pytest.skip("fn_802461BC_pcdump.txt fixture not present")
    events = parse_hook_events(fpath.read_text())
    fev = find_function(events, "mnDiagram3_8024714C")
    assert fev is not None
    section = fd.select_class_section(fev, class_id=0)
    assert section is not None
    views = fd.decision_views(section, fev)
    assert len(views) > 0
    assert all(isinstance(v, fd.DecisionView) for v in views)


def test_target_identity_set_is_force_phys_keys():
    target = fd.TargetColoring(class_id=0, force_phys={42: 28, 38: 28, 34: 31})
    assert fd.target_identity_set(target) == {42, 38, 34}


def test_decision_views_spill_comes_from_simplify_not_colorgraph_bit0():
    class _D:
        def __init__(self, ig, flags):
            self.ig_idx, self.iter_idx, self.assigned_reg = ig, 0, 5
            self.n_interferers, self.flags, self.interferers = 0, flags, []
    class _Sec:
        def __init__(self, cid, decisions):
            self.class_id, self.decisions = cid, decisions
    class _SE:
        def __init__(self, ig, spilled):
            self.ig_idx, self.spilled = ig, spilled
    class _SimpSec:
        def __init__(self, cid, entries):
            self.class_id, self.entries = cid, entries
    class _Fev:
        def __init__(self, cg, simp):
            self.colorgraph_sections, self.simplify_sections = cg, simp
    sec = _Sec(0, [_D(10, 0x1), _D(11, 0x0)])          # ig 10 has colorgraph bit0 set
    fev = _Fev([sec], [_SimpSec(0, [_SE(11, True)])])  # only ig 11 is simplify-spilled
    views = {v.ig_idx: v for v in fd.decision_views(sec, fev)}
    assert views[10].spilled is False   # colorgraph bit0 ignored
    assert views[11].spilled is True    # simplify SPILLED honored


class _FakeAliasSection:
    def __init__(self, class_id, aliases):
        self.class_id = class_id
        self.aliases = aliases  # list of (alias_idx, root_idx, root_phys)


class _FakeSimplifyEntry:
    def __init__(self, ig_idx, spilled):
        self.ig_idx = ig_idx
        self.spilled = spilled


class _FakeSimplifySection:
    def __init__(self, class_id, entries):
        self.class_id = class_id
        self.entries = entries


class _FakeFunctionEvents:
    def __init__(self, name, colorgraph_sections, coalesced_alias_sections=(),
                 coalesce_sections=(), simplify_sections=()):
        self.name = name
        self.colorgraph_sections = list(colorgraph_sections)
        self.coalesced_alias_sections = list(coalesced_alias_sections)
        self.coalesce_sections = list(coalesce_sections)
        self.simplify_sections = list(simplify_sections)


def _present_views(*ig_idxs):
    # build a class-0 section whose decisions cover the given ig_idxs
    class _Sec:
        class_id = 0
        decisions = []
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=ig, iter_idx=i, assigned_reg=29, degree=0,
                           n_interferers=0, flags=0, interferers=[]))()
        for i, ig in enumerate(ig_idxs)
    ]
    return sec


def test_step1a_detects_coalesced_case_d():
    sec = _present_views(34, 37, 32, 52)  # 42 and 38 are NOT present (coalesced)
    fev = _FakeFunctionEvents(
        "gm", [sec],
        coalesced_alias_sections=[_FakeAliasSection(0, [(42, 3, 3), (38, 3, 3)])],
    )
    target = fd.TargetColoring(class_id=0, force_phys={34: 31, 37: 30, 32: 29,
                                                       42: 28, 52: 28, 38: 28})
    absent = fd.find_absent_targets(fev, target)
    assert absent is not None
    assert absent.case == fd.DivergenceCase.D_COALESCED
    assert set(absent.coalesced_nodes) == {42, 38}
    assert absent.coalesced_root == 3
    assert absent.coalesced_root_phys == 3


def test_step1a_detects_spilled_case_e():
    sec = _present_views(34, 37)  # 99 absent, and spilled
    fev = _FakeFunctionEvents(
        "f", [sec],
        simplify_sections=[_FakeSimplifySection(0, [_FakeSimplifyEntry(99, True)])],
    )
    target = fd.TargetColoring(class_id=0, force_phys={34: 31, 99: 28})
    absent = fd.find_absent_targets(fev, target)
    assert absent is not None
    assert absent.case == fd.DivergenceCase.E_SPILLED
    assert absent.ig_idx == 99


def test_step1a_returns_none_when_all_present():
    sec = _present_views(44, 46)
    fev = _FakeFunctionEvents("lbDvd", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={44: 10, 46: 12})
    assert fd.find_absent_targets(fev, target) is None


def test_step1a_coalesced_into_on_target_root_is_satisfied():
    """Regression: a target node coalesced into a root that ALREADY holds the
    node's target register is on-target, NOT Case D. This is the natural-self
    negative-control case — `target derive` emits each alias key at its root's
    phys, so feeding the derived map straight back must report no divergence."""
    sec = _present_views(34, 37)  # present nodes (assigned_reg=29) on-target below
    fev = _FakeFunctionEvents(
        "f", [sec],
        coalesced_alias_sections=[_FakeAliasSection(0, [(42, 3, 3), (38, 3, 3)])],
    )
    # aliases 42/38 want r3 == their root's phys -> satisfied via coalescing
    target = fd.TargetColoring(class_id=0,
                               force_phys={34: 29, 37: 29, 42: 3, 38: 3})
    assert fd.find_absent_targets(fev, target) is None


def test_step1a_case_d_only_for_off_target_coalesced_node():
    """When nodes share a coalesce root, only the one whose target differs from
    the root's phys is a Case D divergence; the on-target one is skipped."""
    sec = _present_views(34)
    fev = _FakeFunctionEvents(
        "f", [sec],
        coalesced_alias_sections=[_FakeAliasSection(0, [(42, 3, 3), (38, 3, 3)])],
    )
    # 42 wants r3 (== root, satisfied); 38 wants r28 (off-target -> Case D)
    target = fd.TargetColoring(class_id=0, force_phys={34: 29, 42: 3, 38: 28})
    absent = fd.find_absent_targets(fev, target)
    assert absent is not None
    assert absent.case == fd.DivergenceCase.D_COALESCED
    assert set(absent.coalesced_nodes) == {38}
    assert 42 not in absent.coalesced_nodes


def test_decision_coloring_excludes_r0_spilled_and_sentinel():
    """decision_coloring keeps only independently-colored decision nodes at a
    real register r1..r31. r0 (model boundary), spilled nodes, the -1 sentinel,
    and placeholder/out-of-range regs are dropped."""
    def _d(ig, reg):
        return type("D", (), dict(ig_idx=ig, iter_idx=0, assigned_reg=reg,
                                  n_interferers=0, flags=0, interferers=[]))()
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [_d(5, 4), _d(6, 0), _d(7, 9), _d(-1, 4), _d(8, -999)]
    fev = _FakeFunctionEvents(
        "f", [sec],
        simplify_sections=[_FakeSimplifySection(0, [_FakeSimplifyEntry(7, True)])],
    )
    # 6=r0, 7=spilled, -1=sentinel, 8=out-of-range all dropped; only 5 kept.
    assert fd.decision_coloring(fev, 0) == {5: 4}


def test_decision_coloring_retains_fpr_f0_for_class_one():
    def _d(ig, reg):
        return type("D", (), dict(ig_idx=ig, iter_idx=0, assigned_reg=reg,
                                  n_interferers=0, flags=0, interferers=[]))()

    class _Sec:
        class_id = 1

    sec = _Sec()
    sec.decisions = [_d(5, 0), _d(6, 32), _d(-1, 4)]
    fev = _FakeFunctionEvents("f", [sec])

    assert fd.decision_coloring(fev, 1) == {5: 0}


def test_decision_coloring_round_trips_to_none():
    """A target built from decision_coloring is faithful: feeding it straight
    back reports no divergence (the force-phys-safe natural-self path)."""
    sec = _present_views(34, 37)  # decisions assigned_reg=29
    fev = _FakeFunctionEvents("f", [sec])
    coloring = fd.decision_coloring(fev, 0)
    assert coloring == {34: 29, 37: 29}
    report = fd.analyze_first_divergence(
        fev, fd.TargetColoring(class_id=0, force_phys=coloring))
    assert report.fact.case == fd.DivergenceCase.NONE


def _view(ig, it, reg, interferers=(), n=None):
    return fd.DecisionView(ig_idx=ig, iter_idx=it, assigned_reg=reg,
                           n_interferers=(len(interferers) if n is None else n),
                           interferers=tuple(interferers), spilled=False)


def test_step1b_finds_first_mapped_divergence_in_iter_order():
    views = [_view(44, 0, 12), _view(46, 1, 10), _view(99, 2, 5)]
    target = fd.TargetColoring(class_id=0, force_phys={44: 10, 46: 12})
    point = fd.find_register_choice_divergence(views, target)
    assert point is not None
    assert point.ig_idx == 44          # lowest iter among mismatching mapped nodes
    assert point.baseline_reg == 12
    assert point.target_reg == 10


def test_step1b_none_when_all_mapped_on_target():
    views = [_view(44, 0, 10), _view(46, 1, 12)]
    target = fd.TargetColoring(class_id=0, force_phys={44: 10, 46: 12})
    assert fd.find_register_choice_divergence(views, target) is None


def test_replay_lowest_set_bit_pick():
    # one decision, interferer holds r3 (precolored: ig 99 has no decision) -> pick r4
    views = [_view(5, 0, 4, interferers=((99, 3),))]
    steps = {s.ig_idx: s for s in fd.replay_decisions(views)}
    assert steps[5].predicted_reg == 4
    assert steps[5].dispensed is False
    assert 3 not in steps[5].working_mask
    assert 3 in steps[5].blockers


def test_replay_dispenses_top_down_when_volatiles_blocked():
    # node 0 interferes with precolored r3..r12 -> volatile pool empty -> dispense r31
    blockers = tuple((900 + k, r) for k, r in enumerate(range(3, 13)))
    views = [_view(0, 0, 31, interferers=blockers)]
    steps = {s.ig_idx: s for s in fd.replay_decisions(views)}
    assert steps[0].predicted_reg == 31
    assert steps[0].dispensed is True


def test_replay_reuses_dispensed_callee_save():
    # iter0: node A blocks all volatiles -> dispenses r31 (added to pool)
    # iter1: node B blocks all volatiles too, but NOT r31 -> reuses r31 via lowest-bit
    block_vol = tuple((900 + k, r) for k, r in enumerate(range(3, 13)))
    views = [
        _view(0, 0, 31, interferers=block_vol),
        _view(1, 1, 31, interferers=block_vol),   # r31 free for reuse
    ]
    steps = {s.ig_idx: s for s in fd.replay_decisions(views)}
    assert steps[0].predicted_reg == 31 and steps[0].dispensed is True
    assert steps[1].predicted_reg == 31 and steps[1].dispensed is False  # REUSE


def test_replay_marks_cap_hit():
    views = [_view(5, 0, 4, interferers=((99, 3),), n=82)]  # row truncated
    steps = {s.ig_idx: s for s in fd.replay_decisions(views)}
    assert steps[5].cap_hit is True


def test_replay_ignores_virtual_and_negative_interferer_regs():
    # interferer ig not a decision, reg >31 (virtual leak) or <0 -> not a blocker
    views = [_view(5, 0, 3, interferers=((900, 51), (901, -1)))]
    steps = {s.ig_idx: s for s in fd.replay_decisions(views)}
    assert steps[5].predicted_reg == 3
    assert steps[5].blockers == frozenset()
    assert steps[5].unreliable is False


def test_replay_flags_unreliable_on_missing_callee_save_interferer():
    # interferer ig not a decision, holds r26 (callee-save) -> incomplete table
    views = [_view(5, 0, 3, interferers=((900, 26),))]
    steps = {s.ig_idx: s for s in fd.replay_decisions(views)}
    assert steps[5].unreliable is True
    assert 26 in steps[5].blockers


def test_fpr_replay_treats_missing_f13_as_volatile_not_incomplete():
    # FPR class 1 has f0..f13 in the initial volatile set. The GPR replay
    # boundary used to treat f13 as callee-save and falsely abstain on FPR
    # residuals whose interferences mention precolored f13.
    views = [_view(39, 0, 28, interferers=((900, 13),))]

    steps = {s.ig_idx: s for s in fd.replay_decisions(views, class_id=1)}

    assert 13 in steps[39].blockers
    assert steps[39].unreliable is False


def test_fpr_replay_flags_unreliable_on_missing_f14_interferer():
    views = [_view(39, 0, 28, interferers=((900, 14),))]

    steps = {s.ig_idx: s for s in fd.replay_decisions(views, class_id=1)}

    assert 14 in steps[39].blockers
    assert steps[39].unreliable is True


def test_fpr_callee_save_swap_classifies_instead_of_abstaining():
    class _Sec:
        class_id = 1

    volatile_fprs = tuple((900 + reg, reg) for reg in range(14))
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=37, iter_idx=0, assigned_reg=31, degree=0,
                           n_interferers=len(volatile_fprs), flags=0,
                           interferers=volatile_fprs))(),
        type("D", (), dict(ig_idx=53, iter_idx=1, assigned_reg=30, degree=0,
                           n_interferers=len(volatile_fprs), flags=0,
                           interferers=volatile_fprs))(),
        type("D", (), dict(ig_idx=52, iter_idx=2, assigned_reg=29, degree=0,
                           n_interferers=len(volatile_fprs), flags=0,
                           interferers=volatile_fprs))(),
        type("D", (), dict(
            ig_idx=39, iter_idx=3, assigned_reg=28, degree=0,
            n_interferers=len(volatile_fprs) + 4, flags=0,
            interferers=volatile_fprs + ((37, 31), (52, 29), (53, 30), (33, 26)),
        ))(),
        type("D", (), dict(
            ig_idx=33, iter_idx=4, assigned_reg=26, degree=0,
            n_interferers=len(volatile_fprs) + 4, flags=0,
            interferers=volatile_fprs + ((37, 31), (39, 28), (52, 29), (53, 30)),
        ))(),
    ]
    fev = _FakeFunctionEvents("fpr", [sec])
    target = fd.TargetColoring(class_id=1, force_phys={33: 28, 39: 26})

    report = fd.analyze_first_divergence(fev, target)

    assert report.fact.case == fd.DivergenceCase.C2_STICKY_POOL
    assert report.fact.ig_idx == 39


def test_fpr_f0_is_not_the_gpr_r0_model_boundary():
    class _Sec:
        class_id = 1

    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=44, iter_idx=0, assigned_reg=1, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
    ]
    fev = _FakeFunctionEvents("fpr", [sec])
    target = fd.TargetColoring(class_id=1, force_phys={44: 0})

    report = fd.analyze_first_divergence(fev, target)

    assert report.fact.case != fd.DivergenceCase.ABSTAINED
    assert report.fact.target_reg == 0


def _step(ig, working, blockers=()):
    return fd.ReplayStep(ig_idx=ig, iter_idx=0, working_mask=frozenset(working),
                         predicted_reg=min(working) if working else -1,
                         dispensed=not working, cap_hit=False,
                         blockers=frozenset(blockers), unreliable=False)


def test_classify_case_a_blocked():
    point = fd.DivergencePoint(ig_idx=5, iter_idx=3, baseline_reg=4, target_reg=3)
    step = _step(5, working={4, 5}, blockers={3})       # r3 (target) blocked
    target = fd.TargetColoring(class_id=0, force_phys={5: 3})
    fact = fd.classify_divergence(point, step, target, views_by_ig={},
                                  interferers=((9, 3),))
    assert fact.case == fd.DivergenceCase.A_BLOCKED
    assert fact.blocker_ig == 9


def test_classify_case_b_target_higher():
    point = fd.DivergencePoint(ig_idx=5, iter_idx=1, baseline_reg=3, target_reg=5)
    step = _step(5, working={3, 5})                     # both free, took lower (3)
    target = fd.TargetColoring(class_id=0, force_phys={5: 5})
    fact = fd.classify_divergence(point, step, target, views_by_ig={}, interferers=())
    assert fact.case == fd.DivergenceCase.B_TARGET_HIGHER


def test_classify_case_b_inverse():
    point = fd.DivergencePoint(ig_idx=5, iter_idx=1, baseline_reg=30, target_reg=5)
    step = _step(5, working=set(), blockers={3, 4, 6, 7, 8, 9, 10, 11, 12})
    target = fd.TargetColoring(class_id=0, force_phys={5: 5})
    fact = fd.classify_divergence(point, step, target, views_by_ig={}, interferers=())
    assert fact.case == fd.DivergenceCase.B_INVERSE


def test_classify_case_c_dispense_order():
    point = fd.DivergencePoint(ig_idx=5, iter_idx=4, baseline_reg=31, target_reg=30)
    step = _step(5, working=set())                      # dispensed, no later r30
    target = fd.TargetColoring(class_id=0, force_phys={5: 30})
    fact = fd.classify_divergence(point, step, target, views_by_ig={}, interferers=())
    assert fact.case == fd.DivergenceCase.C_DISPENSE_ORDER


def test_classify_case_c2_sticky_pool():
    point = fd.DivergencePoint(ig_idx=5, iter_idx=2, baseline_reg=31, target_reg=30)
    step = _step(5, working=set())                      # dispensed
    # a LATER decision (iter 4) holds r30 -> target could sticky-pool it by X's turn
    later = fd.DecisionView(ig_idx=8, iter_idx=4, assigned_reg=30,
                            n_interferers=0, interferers=(), spilled=False)
    target = fd.TargetColoring(class_id=0, force_phys={5: 30})
    fact = fd.classify_divergence(point, step, target,
                                  views_by_ig={8: later}, interferers=())
    assert fact.case == fd.DivergenceCase.C2_STICKY_POOL


def test_local_target_strings_per_case():
    assert "prevent the coalesce" in fd.local_target_for(
        fd.DivergenceCase.D_COALESCED, coalesced_nodes=(42, 38), root=3)
    assert "interference degree" in fd.local_target_for(fd.DivergenceCase.E_SPILLED)
    assert "structural" in fd.local_target_for(fd.DivergenceCase.ABSENT).lower()
    a = fd.local_target_for(fd.DivergenceCase.A_BLOCKED, blocker_ig=9,
                            blocker_dependency=False)
    assert "interference" in a and "process X" in a
    a_dep = fd.local_target_for(fd.DivergenceCase.A_BLOCKED, blocker_ig=9,
                                blocker_dependency=True)
    assert "recolor" in a_dep.lower()
    assert "simplify order" in fd.local_target_for(fd.DivergenceCase.B_TARGET_HIGHER)
    assert "earlier" in fd.local_target_for(fd.DivergenceCase.B_INVERSE)
    assert "simplify-order" in fd.local_target_for(fd.DivergenceCase.C_DISPENSE_ORDER)
    assert "nonvolatiles dispense" in fd.local_target_for(fd.DivergenceCase.C2_STICKY_POOL)


def test_format_report_uses_fpr_register_prefix_for_class_one():
    fact = fd.AllocatorFact(
        class_id=1, ig_idx=39, case=fd.DivergenceCase.C2_STICKY_POOL,
        iter_idx=26, baseline_reg=28, target_reg=26, coalesced_nodes=(),
        coalesced_root=None, coalesced_root_phys=None, blocker_ig=None,
        blocker_dependency=False, working_mask=frozenset(), cap_hit=False,
        earlier_unmapped_warning=False, local_target="shift FPR dispense order",
    )

    rendered = fd.format_report(fd.FirstDivergenceReport(fact=fact, source=None))

    assert "baseline: ig 39 -> f28" in rendered
    assert "target:   ig 39 -> f26" in rendered
    assert "r28" not in rendered


def test_analyze_gm_like_returns_case_d():
    sec = _present_views(34, 37, 32, 52)
    fev = _FakeFunctionEvents(
        "gm", [sec],
        coalesced_alias_sections=[_FakeAliasSection(0, [(42, 3, 3), (38, 3, 3)])],
    )
    target = fd.TargetColoring(class_id=0, force_phys={34: 31, 37: 30, 32: 29,
                                                       42: 28, 52: 28, 38: 28})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case == fd.DivergenceCase.D_COALESCED
    assert set(report.fact.coalesced_nodes) == {42, 38}
    assert report.source is None


def test_analyze_lbdvd_like_returns_register_choice():
    # baseline 44->r12, 46->r10 ; target wants 44->r10, 46->r12
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=44, iter_idx=0, assigned_reg=12, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
        type("D", (), dict(ig_idx=46, iter_idx=1, assigned_reg=10, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
    ]
    fev = _FakeFunctionEvents("lbDvd", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={44: 10, 46: 12})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case in (fd.DivergenceCase.B_TARGET_HIGHER,
                                fd.DivergenceCase.B_INVERSE)
    assert report.fact.ig_idx in (44, 46)


def test_analyze_no_divergence_is_case_none():
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=44, iter_idx=0, assigned_reg=10, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
    ]
    fev = _FakeFunctionEvents("f", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={44: 10})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case == fd.DivergenceCase.NONE


def test_analyze_abstains_on_r0_divergence():
    # baseline assigns r0 (model boundary); target wants r5 -> ABSTAINED, not classified
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=44, iter_idx=0, assigned_reg=0, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
    ]
    fev = _FakeFunctionEvents("f", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={44: 5})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case == fd.DivergenceCase.ABSTAINED


def test_analyze_continues_past_r0_boundary_to_next_target_divergence():
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=58, iter_idx=0, assigned_reg=0, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
        type("D", (), dict(ig_idx=34, iter_idx=1, assigned_reg=29, degree=0,
                           n_interferers=0, flags=0, interferers=[]))(),
    ]
    fev = _FakeFunctionEvents("f", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={58: 4, 34: 30})

    report = fd.analyze_first_divergence(fev, target)

    assert report.fact.case is not fd.DivergenceCase.ABSTAINED
    assert report.fact.ig_idx == 34
    assert "continued past r0-boundary target ig 58" in report.fact.local_target


def test_analyze_abstains_on_cap_hit():
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=44, iter_idx=0, assigned_reg=5, degree=0,
                           n_interferers=82, flags=0, interferers=[(99, 3)]))(),
    ]
    fev = _FakeFunctionEvents("f", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={44: 10})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case == fd.DivergenceCase.ABSTAINED
    assert report.fact.cap_hit is True
    assert "truncated" in report.fact.local_target


def test_analyze_abstains_on_unreliable():
    class _Sec:
        class_id = 0
    sec = _Sec()
    sec.decisions = [
        type("D", (), dict(ig_idx=44, iter_idx=0, assigned_reg=5, degree=0,
                           n_interferers=1, flags=0, interferers=[(900, 26)]))(),
    ]
    fev = _FakeFunctionEvents("f", [sec])
    target = fd.TargetColoring(class_id=0, force_phys={44: 10})
    report = fd.analyze_first_divergence(fev, target)
    assert report.fact.case == fd.DivergenceCase.ABSTAINED
    assert report.fact.cap_hit is False
    assert "missing node" in report.fact.local_target


def test_attach_source_ideas_degrades_when_no_bindings(monkeypatch):
    monkeypatch.setattr(fd, "_list_bindings_safe", lambda *a, **k: [])
    fact = fd.AllocatorFact(
        class_id=0, ig_idx=42, case=fd.DivergenceCase.D_COALESCED, iter_idx=None,
        baseline_reg=3, target_reg=28, coalesced_nodes=(42, 38), coalesced_root=3,
        coalesced_root_phys=3, blocker_ig=None, blocker_dependency=False,
        working_mask=None, cap_hit=False, earlier_unmapped_warning=False,
        local_target="prevent the coalesce ...")
    idea = fd.attach_source_ideas(fact, source_text="", fn_name="f", pre_pass=None)
    assert idea.ig_idx == 42
    assert idea.var_name is None
    assert idea.ideas  # still emits case-level structural ideas


def test_attach_source_ideas_ranks_alternates(monkeypatch):
    class _B:
        def __init__(self, name, virtual, conf, scope):
            self.var_name, self.virtual, self.confidence, self.scope_path = (
                name, virtual, conf, scope)
            self.decl_line, self.kind, self.type_str = 0, "local", "s32"
    monkeypatch.setattr(fd, "_list_bindings_safe", lambda *a, **k: [
        _B("c2", 42, "low-confidence", ("fn", "block@1")),
        _B("c1", 42, "best-guess", ("fn",)),
        _B("other", 7, "verified", ("fn",)),
    ])
    fact = fd.AllocatorFact(
        class_id=0, ig_idx=42, case=fd.DivergenceCase.A_BLOCKED, iter_idx=3,
        baseline_reg=4, target_reg=3, coalesced_nodes=(), coalesced_root=None,
        coalesced_root_phys=None, blocker_ig=9, blocker_dependency=False,
        working_mask=frozenset({4}), cap_hit=False, earlier_unmapped_warning=False,
        local_target="eliminate the X-Y interference ...")
    idea = fd.attach_source_ideas(fact, source_text="...", fn_name="f",
                                  pre_pass=object())
    assert idea.var_name == "c1"                 # best-guess outranks low-confidence
    assert idea.confidence == "best-guess"
    assert "c2" in idea.alternates
    assert "other" not in idea.alternates        # different virtual filtered out


def test_attach_source_ideas_includes_blocker_context(monkeypatch):
    class _B:
        def __init__(self, name, virtual, conf, scope):
            self.var_name, self.virtual, self.confidence, self.scope_path = (
                name, virtual, conf, scope)
            self.decl_line, self.kind, self.type_str = 0, "local", "s32"

    class _FD:
        block_idx = 2
        opcode = "lwz"
        operands = "r46,pl_804D6470(r0)"
        annotations = ["fIsPtrOp"]

    monkeypatch.setattr(fd, "_list_bindings_safe", lambda *a, **k: [
        _B("target", 36, "best-guess", ("fn",)),
        _B("nested_late", 36, "ambiguous-nested", ("fn", "block@l40c8")),
    ])
    monkeypatch.setattr(fd, "_first_def_summary", lambda ig, pre: (
        "B2: lwz r46,pl_804D6470(r0)" if ig == 46 else None
    ))
    fact = fd.AllocatorFact(
        class_id=0, ig_idx=36, case=fd.DivergenceCase.A_BLOCKED, iter_idx=3,
        baseline_reg=31, target_reg=29, coalesced_nodes=(), coalesced_root=None,
        coalesced_root_phys=None, blocker_ig=46, blocker_dependency=False,
        working_mask=frozenset({29}), cap_hit=False, earlier_unmapped_warning=False,
        local_target="eliminate the X-Y interference ...")

    idea = fd.attach_source_ideas(fact, source_text="...", fn_name="fn",
                                  pre_pass=object())
    assert idea.var_name == "target"
    assert "nested_late" in " ".join(idea.rejected)
    assert idea.blocker_ig == 46
    assert idea.blocker_first_def == "B2: lwz r46,pl_804D6470(r0)"

    rendered = fd.format_report(fd.FirstDivergenceReport(fact=fact, source=idea))
    assert "blocker ig 46" in rendered
    assert "B2: lwz r46,pl_804D6470(r0)" in rendered


def test_attach_source_ideas_uses_fpr_expression_source(monkeypatch):
    class _Source:
        kind = "local"
        confidence = "fpr-expression-order"
        name = "row_offset"
        expression = "y_offset * row"
        source_file = "sample.c"
        source_line = 12
        source_col = 18
        first_def = None

    monkeypatch.setattr(fd, "_list_bindings_safe", lambda *a, **k: [])
    monkeypatch.setattr(
        fd,
        "_source_attribution_for_ig",
        lambda *a, **k: _Source(),
        raising=False,
    )
    fact = fd.AllocatorFact(
        class_id=1, ig_idx=39, case=fd.DivergenceCase.C2_STICKY_POOL,
        iter_idx=3, baseline_reg=28, target_reg=26,
        coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
        blocker_ig=None, blocker_dependency=False,
        working_mask=frozenset(), cap_hit=False,
        earlier_unmapped_warning=False, local_target="shift FPR dispense order")

    idea = fd.attach_source_ideas(
        fact, source_text="...", fn_name="fn", pre_pass=object(),
        source_file="sample.c")

    assert idea.source_kind == "local"
    assert idea.source_expression == "y_offset * row"
    assert any("FPR" in text and "row_offset" in text for text in idea.ideas)

    rendered = fd.format_report(fd.FirstDivergenceReport(fact=fact, source=idea))
    assert "sample.c:12:18" in rendered
    assert "y_offset * row" in rendered


def test_attach_source_ideas_reports_implicit_address_temp_spans(monkeypatch):
    class _Binding:
        def __init__(self, name, virtual, line):
            self.var_name = name
            self.virtual = virtual
            self.confidence = "best-guess"
            self.scope_path = ("fn",)
            self.decl_line = line
            self.kind = "local"
            self.type_str = "s32"

    class _Site:
        pass

    site = _Site()
    site.block_idx = 14
    site.opcode = "add"
    site.operands = "r44,r51,r34"

    class _Source:
        kind = "implicit-temp"
        confidence = "pcode-first-def"
        name = None
        expression = "add r44,r51,r34"
        source_file = "sample.c"
        source_line = None
        source_col = None
        first_def = site

    monkeypatch.setattr(fd, "_list_bindings_safe", lambda *a, **k: [
        _Binding("base", 51, 40),
        _Binding("index", 34, 41),
    ])
    monkeypatch.setattr(
        fd,
        "_source_attribution_for_ig",
        lambda *a, **k: _Source(),
        raising=False,
    )
    fact = fd.AllocatorFact(
        class_id=0, ig_idx=44, case=fd.DivergenceCase.C_DISPENSE_ORDER,
        iter_idx=29, baseline_reg=27, target_reg=25,
        coalesced_nodes=(), coalesced_root=None, coalesced_root_phys=None,
        blocker_ig=None, blocker_dependency=False,
        working_mask=frozenset(), cap_hit=False,
        earlier_unmapped_warning=False,
        local_target="shift address temp simplify order")

    idea = fd.attach_source_ideas(
        fact, source_text="...", fn_name="fn", pre_pass=object(),
        source_file="sample.c")

    assert idea.source_kind == "implicit-temp"
    assert "sample.c:40" in idea.candidate_spans[0]
    assert "base" in idea.candidate_spans[0]
    assert "sample.c:41" in idea.candidate_spans[1]
    assert any("indexed-pointer-loop" in text for text in idea.ideas)

    rendered = fd.format_report(fd.FirstDivergenceReport(fact=fact, source=idea))
    assert "candidate spans:" in rendered
    assert "base" in rendered
    assert "index" in rendered


def test_list_bindings_safe_passes_args_in_order(monkeypatch):
    """Regression for the --source mis-wiring: _list_bindings_safe must call
    list_bindings(source, fn_name, pre_pass) in that order. The original bug
    passed the FunctionEvents object as the fn_name."""
    import src.mwcc_debug.symbol_bridge as sb
    captured = {}
    def _fake(source, fn_name, pre_pass):
        captured.update(source=source, fn_name=fn_name, pre_pass=pre_pass)
        return []
    monkeypatch.setattr(sb, "list_bindings", _fake)
    fd._list_bindings_safe("SRC", "myFunc", "PRE")
    assert captured == {"source": "SRC", "fn_name": "myFunc", "pre_pass": "PRE"}


def test_list_bindings_safe_degrades_without_source_or_prepass(monkeypatch):
    """No source text or no pre-pass -> [] without even calling the bridge."""
    import src.mwcc_debug.symbol_bridge as sb
    def _boom(*a, **k):
        raise AssertionError("list_bindings should not be called")
    monkeypatch.setattr(sb, "list_bindings", _boom)
    assert fd._list_bindings_safe("", "f", object()) == []
    assert fd._list_bindings_safe("SRC", "f", None) == []


def test_parse_force_phys_map():
    assert fd.parse_force_phys_arg("42:28,38:28,34:31") == {42: 28, 38: 28, 34: 31}
    assert fd.parse_force_phys_arg("gpr:42:28,fp:5:3") == {42: 28, 5: 3}  # class prefix dropped


def test_format_report_has_gated_and_advisory_sections():
    fact = fd.AllocatorFact(
        class_id=0, ig_idx=42, case=fd.DivergenceCase.D_COALESCED, iter_idx=None,
        baseline_reg=3, target_reg=28, coalesced_nodes=(42, 38), coalesced_root=3,
        coalesced_root_phys=3, blocker_ig=None, blocker_dependency=False,
        working_mask=None, cap_hit=False, earlier_unmapped_warning=False,
        local_target="prevent the coalesce ...")
    report = fd.FirstDivergenceReport(fact=fact, source=None)
    text = fd.format_report(report)
    assert "ALLOCATOR FACTS" in text and "Case D" in text
    assert "42" in text and "38" in text
    assert "ADVISORY" in text  # advisory section header present even when source is None
