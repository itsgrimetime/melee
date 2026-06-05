import pathlib, pytest
from src.mwcc_debug import role_descriptor as rd
from src.mwcc_debug import convergence as cv
from src.mwcc_debug.progress_classifier import IterationState

FIX = pathlib.Path(__file__).parent / "fixtures" / "role_identity"


def test_analyze_iteration_builds_state_from_corpus_pair():
    """analyze_iteration: build a target from the matched rev, then analyze the
    drifted (wip) compile against it — producing an IterationState whose diverging
    node (if any) is identified as a target role with a role_order_rank."""
    fn = "mnVibration_80248644"
    mp, wp = FIX / "mnVibration_matched_pcdump.txt", FIX / "mnVibration_wip_pcdump.txt"
    if not (mp.exists() and wp.exists()):
        pytest.skip("corpus missing")
    mc = rd.Compile.from_text(mp.read_text(), fn, "")
    wc = rd.Compile.from_text(wp.read_text(), fn, "")
    md = rd.build_descriptors(mc, 0)
    desired = {ig: 13 + i for i, ig in enumerate(list(md)[:6])}
    target = rd.build_target_spec(mc, desired, 0, "force_proof_proxy", provenance={})
    state = cv.analyze_iteration(target, wc, class_id=0)
    assert isinstance(state, IterationState)
    # the diverging node, when present, is mapped to a target role identity (or None
    # when first-divergence reports NONE / a non-target node)
    assert state.fact is not None
    if state.identity is not None:
        assert isinstance(state.role_order_rank, int)


def test_gone_statuses_cover_matcher_nonmatched():
    # Every non-MATCHED matcher status meaning a tracked role can no longer be
    # confidently followed must count as gone, so the deferred loop sees
    # ROLE_GONE/CYCLE signals (AMBIGUOUS is reachable and must be included).
    assert {"gone", "merged", "split", "ambiguous", "non_comparable"} <= cv._GONE_STATUSES


def test_analyze_iteration_full_exposes_report_and_reanchor():
    """analyze_iteration_full returns (state, report, reanchor_result); the existing
    analyze_iteration is exactly its first element."""
    fn = "mnVibration_80248644"
    mp, wp = FIX / "mnVibration_matched_pcdump.txt", FIX / "mnVibration_wip_pcdump.txt"
    if not (mp.exists() and wp.exists()):
        pytest.skip("corpus missing")
    mc = rd.Compile.from_text(mp.read_text(), fn, "")
    wc = rd.Compile.from_text(wp.read_text(), fn, "")
    md = rd.build_descriptors(mc, 0)
    target = rd.build_target_spec(mc, {ig: 13 + i for i, ig in enumerate(list(md)[:6])},
                                  0, "force_proof_proxy", provenance={})
    state, report, res = cv.analyze_iteration_full(target, wc, class_id=0)
    # analyze_iteration is exactly analyze_iteration_full(...)[0] (frozen dataclass -> ==)
    assert state == cv.analyze_iteration(target, wc, class_id=0)
    assert res is not None and isinstance(res.matched, dict)
    # report is a FirstDivergenceReport when force_phys is non-empty, else None
    assert (report is None) == (len(res.force_phys) == 0)
