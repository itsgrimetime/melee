import pathlib
import pytest
from src.mwcc_debug import convergence_loop as cl
from src.mwcc_debug import role_descriptor as rd
from src.mwcc_debug.progress_classifier import ProgressLabel as L, IterationState, FactView
from src.mwcc_debug.first_divergence import DivergenceCase as DC

# ---------------------------------------------------------------------------
# Task 2: Pure-helper tests
# ---------------------------------------------------------------------------

def _rec(label, **kw):
    base = dict(iteration=0, label=label, case=DC.B_TARGET_HIGHER, identity=10,
                role_order_rank=5, diverging_identity_confident=True,
                non_comparable_reason=None, predicted_lever=None,
                edit_was_order_change=False, checkdiff_clean=False,
                reanchor_matched=6, reanchor_total=6, gone_roles=(), rationale="")
    base.update(kw)
    return cl.IterationRecord(**base)


def test_stalled_fires_on_k_nonprogress_without_rank_improvement():
    recs = [_rec(L.SAME), _rec(L.NON_COMPARABLE), _rec(L.ROLE_GONE)]
    assert cl._stalled(recs, k=3)

def test_stalled_resets_on_moved_later_in_window():
    recs = [_rec(L.SAME), _rec(L.MOVED_LATER), _rec(L.NON_COMPARABLE)]
    assert not cl._stalled(recs, k=3)          # rank improved inside the window

def test_stalled_needs_full_window():
    assert not cl._stalled([_rec(L.SAME), _rec(L.SAME)], k=3)

def test_non_comparable_reason_order_change_beats_identity():
    assert cl._non_comparable_reason(edit_was_order_change=True, identity=None,
                                     curr_rank=None, prev_rank=None) == "order_change"

def test_non_comparable_reason_no_identity_or_rank():
    assert cl._non_comparable_reason(False, identity=None, curr_rank=5, prev_rank=5) == "no_identity_or_rank"
    assert cl._non_comparable_reason(False, identity=10, curr_rank=None, prev_rank=5) == "no_identity_or_rank"

def test_non_comparable_reason_same_rank():
    assert cl._non_comparable_reason(False, identity=10, curr_rank=5, prev_rank=5) == "same_rank_diff_case"


# ---------------------------------------------------------------------------
# Task 3: Scripted test harness + happy-path tests
# ---------------------------------------------------------------------------

def _state(case=DC.B_TARGET_HIGHER, identity=10, rank=5, gone=()):
    return IterationState(fact=FactView(case=case, ig_idx=99), identity=identity,
                          role_order_rank=rank, gone_roles=frozenset(gone))


class _FakeRes:                       # stand-in for ReanchorResult
    def __init__(self, matched): self.matched = matched; self.force_phys = matched


def _analyzer(seq):
    """seq: list of (state, matched_count). Returns analyze_fn yielding them in order."""
    it = iter(seq)
    def fn(target, compile, class_id=0):
        state, n = next(it)
        res = _FakeRes({i: i for i in range(n)})
        report = None if n == 0 else object()
        return state, report, res
    return fn


class _ScriptEditor:
    def __init__(self, levers): self._it = iter(levers)
    def edit(self, ctx):
        lever = next(self._it, StopIteration)
        if lever is StopIteration:
            return None
        return cl.EditProposal(new_compile=object(), predicted_lever=lever, rationale="x")


class _Checker:
    def __init__(self, clean_at=None): self.clean_at, self.n = clean_at, -1
    def is_clean(self, compile):
        self.n += 1
        return self.clean_at is not None and self.n >= self.clean_at


class _Target:                        # minimal stand-in for TargetSpec
    def __init__(self, kind="force_proof_proxy", closure=False, coverage=1.0, n_roles=6):
        self.target_kind, self.causal_closure = kind, closure
        self.target_coverage, self.function = coverage, "fn"
        self.roles = [type("R", (), {"original_ig": i, "role_order_rank": i})() for i in range(n_roles)]


def _run(target, analyzer, editor, checker, cap=10, stall_k=3):
    return cl.run_convergence_loop("fn", target, editor, checker,
                                   iteration_cap=cap, analyze_fn=analyzer, stall_k=stall_k)


def test_converged_when_checker_clean_at_iter0():
    res = _run(_Target(), _analyzer([(_state(), 6)]), _ScriptEditor([]), _Checker(clean_at=0))
    assert res.outcome == cl.Outcome.CONVERGED and len(res.iterations) == 1
    assert res.cause_report == ()        # a clean win carries NO candidate causes (spec §5/§6)

def test_budget_when_cap_reached_without_progress():
    seq = [(_state(case=DC.B_TARGET_HIGHER, identity=i, rank=i), 6) for i in range(20)]
    res = _run(_Target(), _analyzer(seq), _ScriptEditor([DC.B_TARGET_HIGHER]*20),
               _Checker(clean_at=None), cap=5, stall_k=99)
    assert res.outcome == cl.Outcome.BUDGET and len(res.iterations) == 5

def test_no_edit_when_editor_declines():
    res = _run(_Target(), _analyzer([(_state(), 6), (_state(identity=11, rank=6), 6)]),
               _ScriptEditor([]), _Checker(clean_at=None))   # editor immediately returns None
    assert res.outcome == cl.Outcome.NO_EDIT


# ---------------------------------------------------------------------------
# Task 4: Outcome-reachability gate + determinism + log faithfulness + integration
# ---------------------------------------------------------------------------

def test_cycle_when_state_revisited():
    # A -> B -> A : the third compile revisits (id, case) of the first
    seq = [(_state(identity=1, case=DC.A_BLOCKED), 6),
           (_state(identity=1, case=DC.B_TARGET_HIGHER), 6),
           (_state(identity=1, case=DC.A_BLOCKED), 6)]
    res = _run(_Target(), _analyzer(seq), _ScriptEditor([DC.A_BLOCKED, DC.B_TARGET_HIGHER]),
               _Checker(clean_at=None))
    assert res.outcome == cl.Outcome.CYCLE

def test_repeating_order_change_is_cycle_not_non_comparable():
    # even under an order-change lever, an exact (id,case) revisit -> CYCLE (checked first)
    seq = [(_state(identity=1, case=DC.A_BLOCKED, rank=3), 6),
           (_state(identity=1, case=DC.B_TARGET_HIGHER, rank=7), 6),
           (_state(identity=1, case=DC.A_BLOCKED, rank=3), 6)]
    res = _run(_Target(), _analyzer(seq),
               _ScriptEditor([DC.C_DISPENSE_ORDER, DC.C_DISPENSE_ORDER]), _Checker(None))
    assert res.outcome == cl.Outcome.CYCLE

def test_unanalyzable_on_empty_reanchor_none():
    res = _run(_Target(), _analyzer([(_state(case=DC.NONE), 0)]), _ScriptEditor([]), _Checker(None))
    assert res.outcome == cl.Outcome.UNANALYZABLE          # NOT *_SATISFIED

def test_unanalyzable_on_abstained():
    res = _run(_Target(), _analyzer([(_state(case=DC.ABSTAINED), 6)]), _ScriptEditor([]), _Checker(None))
    assert res.outcome == cl.Outcome.UNANALYZABLE

def test_unanalyzable_on_analyze_raises():
    def boom(*a, **k): raise ValueError("no section")
    res = _run(_Target(), boom, _ScriptEditor([]), _Checker(None))
    assert res.outcome == cl.Outcome.UNANALYZABLE

def test_proxy_satisfied_vs_target_satisfied():
    proxy = _run(_Target(kind="force_proof_proxy"),
                 _analyzer([(_state(case=DC.NONE), 6)]), _ScriptEditor([]), _Checker(None))
    real = _run(_Target(kind="matched_natural"),
                _analyzer([(_state(case=DC.NONE), 6)]), _ScriptEditor([]), _Checker(None))
    assert proxy.outcome == cl.Outcome.PROXY_SATISFIED
    assert real.outcome == cl.Outcome.TARGET_SATISFIED

def test_stalled_on_role_gone_storm():
    # distinct identity each step (no exact (id,case) repeat -> not CYCLE); each step's
    # prev identity is in curr.gone_roles -> classifier emits ROLE_GONE; ROLE_GONE is a
    # non-progress label (not terminal) so the window fills -> STALLED.
    seq = [(_state(identity=i, case=DC.B_TARGET_HIGHER, gone=(i-1,)), 6) for i in range(1, 8)]
    res = _run(_Target(), _analyzer(seq), _ScriptEditor([DC.B_TARGET_HIGHER]*7),
               _Checker(None), cap=10, stall_k=3)
    assert res.outcome == cl.Outcome.STALLED

def test_determinism_same_inputs_same_result():
    # multi-element gone_roles exercises the set-serialization sorting (spec §7).
    def mk(): return (_Target(), _analyzer([(_state(identity=1, case=DC.A_BLOCKED, gone=(5, 3, 4)), 6),
                                            (_state(identity=1, case=DC.A_BLOCKED, gone=(5, 3, 4)), 6),
                                            (_state(identity=1, case=DC.A_BLOCKED, gone=(5, 3, 4)), 6)]),
                      _ScriptEditor([DC.A_BLOCKED, DC.A_BLOCKED]), _Checker(None))
    r1 = _run(*mk()); r2 = _run(*mk())
    assert r1.outcome == r2.outcome and len(r1.iterations) == len(r2.iterations)
    assert [x.label for x in r1.iterations] == [x.label for x in r2.iterations]
    assert r1.iterations[0].gone_roles == (3, 4, 5)      # sorted -> deterministic serialization
    assert [x.gone_roles for x in r1.iterations] == [x.gone_roles for x in r2.iterations]

def test_log_faithfully_records_lever_and_coverage():
    seq = [(_state(identity=1, case=DC.B_TARGET_HIGHER), 4),
           (_state(identity=2, case=DC.B_TARGET_HIGHER, rank=8), 5)]
    res = _run(_Target(n_roles=6), _analyzer(seq),
               _ScriptEditor([DC.C_DISPENSE_ORDER]), _Checker(None), cap=2, stall_k=99)
    # iteration 1's record sees the prior order-change lever -> edit_was_order_change True
    assert res.iterations[1].edit_was_order_change is True
    assert res.iterations[1].predicted_lever == DC.C_DISPENSE_ORDER
    assert res.iterations[0].reanchor_matched == 4 and res.iterations[0].reanchor_total == 6


def test_integration_real_analyze_fn_on_corpus_pair():
    """One end-to-end run using the REAL analyze_iteration_full over a corpus pair,
    with a scripted editor that returns the same wip compile (no real edit). Proves
    the driver drives the real analyze path without error and produces a LoopResult."""
    FIXC = pathlib.Path(__file__).parent / "fixtures" / "role_identity"
    mp, wp = FIXC / "mnVibration_matched_pcdump.txt", FIXC / "mnVibration_wip_pcdump.txt"
    if not (mp.exists() and wp.exists()):
        pytest.skip("corpus missing")
    fn = "mnVibration_80248644"
    mc = rd.Compile.from_text(mp.read_text(), fn, "")
    wc = rd.Compile.from_text(wp.read_text(), fn, "")
    md = rd.build_descriptors(mc, 0)
    target = rd.build_target_spec(mc, {ig: 13 + i for i, ig in enumerate(list(md)[:6])},
                                  0, "force_proof_proxy", provenance={})
    class _StaticEditor:
        def edit(self, ctx): return cl.EditProposal(new_compile=wc, predicted_lever=ctx.state.fact.case)
    res = cl.run_convergence_loop(fn, target, _StaticEditor(), _Checker(None),
                                  iteration_cap=4, baseline_compile=wc, stall_k=2)
    # A static editor re-feeding the same wip compile makes no progress -> the real
    # analyze path deterministically STALLs (window of non-progress labels).
    assert isinstance(res, cl.LoopResult) and res.outcome == cl.Outcome.STALLED


# ---------------------------------------------------------------------------
# Task 1 (new): driver threads obj_path to checker
# ---------------------------------------------------------------------------

def test_driver_threads_obj_path_to_checker():
    """The driver checks baseline_obj at iter 0, then each proposal.obj_path; the
    Checker (driver-owned) receives the .o artifact, never a verdict from the editor."""
    seen = []
    class _RecordingChecker:
        def is_clean(self, obj_path):
            seen.append(obj_path)
            return False                       # never clean -> loop proceeds
    class _ObjEditor:
        def __init__(self, objs): self._it = iter(objs)
        def edit(self, ctx):
            nxt = next(self._it, None)
            return None if nxt is None else cl.EditProposal(
                new_compile=object(), predicted_lever=DC.B_TARGET_HIGHER, rationale="", obj_path=nxt)
    # 3 analyzer items: iters 0/1/2 each analyze; editor exhausts after 2 edits so iter 2 -> NO_EDIT
    seq = [(_state(identity=1, rank=1), 6), (_state(identity=2, rank=2), 6), (_state(identity=3, rank=3), 6)]
    cl.run_convergence_loop("fn", _Target(), _ObjEditor(["o1", "o2"]), _RecordingChecker(),
                            iteration_cap=3, analyze_fn=_analyzer(seq),
                            baseline_obj="o0", stall_k=99)
    assert seen[0] == "o0"                      # baseline obj checked first
    assert seen[1] == "o1"                      # then the first edit's obj
