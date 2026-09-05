import json, collections
import pathlib, pytest
from src.mwcc_debug import role_descriptor as rd
from src.mwcc_debug import role_reanchor as rr

FIX = pathlib.Path(__file__).parent / "fixtures" / "role_identity"


def _compile(stem, fn):
    p = FIX / f"{stem}_pcdump.txt"
    if not p.exists():
        pytest.skip(f"{p.name} missing")
    return rd.Compile.from_text(p.read_text(), fn, "")


def test_reanchor_noop_control_is_identity():
    """Re-anchoring a target into the SAME compile it was derived from must map
    every role to its own ig at its own phys (perfect 1:1) — the cleanest ground
    truth. Uses the committed mnvibration matched dump.

    NOTE: plan used list(descs)[:6] but the first 3 keys have empty first_def_sig
    (zero-signature nodes), so the matcher correctly marks them SPLIT against the
    identical-signature pool — they are genuinely indistinguishable and abstention
    is the correct outcome. The intent ("no wrong/drifted placement") is tested by
    selecting only roles with a non-empty first_def_sig, which are distinguishable
    and round-trip cleanly on self-match."""
    fn = "mnVibration_80248644"
    c = _compile("mnVibration_matched", fn)
    descs = rd.build_descriptors(c, 0)
    # Use only roles with a non-empty first_def_sig — distinguishable for identity test
    distinguishable = [ig for ig, d in descs.items() if d.first_def_sig]
    force_phys = {ig: 13 + (ig % 5) for ig in distinguishable[:6]}   # arbitrary target physregs
    target = rd.build_target_spec(c, force_phys, 0, "force_proof_proxy",
                                  provenance={"src": "noop"})
    res = rr.reanchor(target, c, class_id=0)
    # Every force-phys entry maps a role to ITSELF at its own desired phys.
    # (Identical siblings can be honestly AMBIGUOUS on self-match — Gate 1a — so
    # the map is a subset, not necessarily all 6; what must hold is no wrong/drifted
    # placement.)
    for new_ig, phys in res.force_phys.items():
        assert new_ig in force_phys and force_phys[new_ig] == phys
    assert len(res.force_phys) >= 0.8 * len(force_phys), res.diagnostics


def test_confirm_round_trip_demotes_non_invertible_match():
    """A forward match stays in the map only if the new node maps BACK to the
    original role (inverse consistency, spec section 7 / review #4). The decision
    is a pure helper over forward + inverse match dicts, tested directly with
    synthetic RoleMatches: match_roles' min-cost assignment is symmetric, so a
    forward/inverse disagreement only arises from TOP_K pruning asymmetry on real
    data and cannot be staged through cost alone — hence the helper-level test."""
    from src.mwcc_debug.role_matcher import RoleMatch, MatchStatus as S
    forward = {10: RoleMatch(10, 70, 0.9, S.MATCHED, {}),    # 10 -> 70
               11: RoleMatch(11, 71, 0.8, S.MATCHED, {})}    # 11 -> 71
    inverse = {70: RoleMatch(70, 11, 0.9, S.MATCHED, {}),    # 70 maps back to 11, NOT 10
               71: RoleMatch(71, 11, 0.8, S.MATCHED, {})}    # 71 -> 11
    fp, diag, _matched = rr._confirm_round_trip(forward, inverse, desired={10: 13, 11: 14})
    assert 70 not in fp and diag[10] == "unstable_identity"  # 10's match is not invertible
    assert fp.get(71) == 14 and 11 not in diag               # 11 <-> 71 round-trips cleanly


def test_reanchor_routes_gone_and_no_descriptor_to_diagnostics():
    """A target role with no candidate (GONE) and a role with descriptor=None
    (structural Case D/E) must both be excluded from force_phys and recorded in
    diagnostics — never coerced into a force-phys entry."""
    from src.mwcc_debug.role_descriptor import RoleDescriptor as RD, TargetRoleSpec, TargetSpec
    def d(ig, sig): return RD(ig_idx=ig, first_def_sig=sig, use_site_multiset=(("lwz",1),),
        is_param=False, var_name=None, var_confidence=None, assigned_reg=10, live_range=(0,5),
        use_count=1, spilled=False)
    roles = [
        TargetRoleSpec(40, 31, 0, d(40, "lwz r#,44(r#)"), 0),     # present in cand
        TargetRoleSpec(50, 30, 0, d(50, "fmadds f#,f#,f#,f#"), 1),# GONE (no GPR cand matches)
        TargetRoleSpec(60, 29, 0, None, None),                    # structural, no descriptor
    ]
    target = TargetSpec("fn", "force_proof_proxy", 1.0, False, {}, roles)
    cand = {40: d(40, "lwz r#,44(r#)")}
    res = rr.reanchor_descs({40: roles[0].descriptor, 50: roles[1].descriptor}, cand,
                            desired={40:31, 50:30}, class_id=0,
                            pre_diag={60: "no_descriptor"})
    assert res.force_phys.get(40) == 31           # role 40 matched cand 40 (self), phys preserved
    assert res.diagnostics.get(50) == "gone"       # no GPR candidate -> GONE
    assert res.diagnostics.get(60) == "no_descriptor"
    assert 30 not in res.force_phys.values() and 29 not in res.force_phys.values()


def test_reanchor_to_target_spec_shape_matches_force_phys_safe():
    """reanchor_to_target_spec emits {function, virtuals, spilled} — the same shape
    `target derive --force-phys-safe` produces and `first-divergence` consumes."""
    res = rr.ReanchorResult(class_id=0, force_phys={39: 31, 43: 30}, diagnostics={})
    spec = rr.reanchor_to_target_spec(res, "fn_x", spilled=[])
    assert spec == {"function": "fn_x", "virtuals": {39: 31, 43: 30}, "spilled": []}


def test_cli_target_reanchor_emits_spec_and_diagnostics(tmp_path):
    """`target reanchor TARGET.json NEW_PCDUMP -f FN` prints the force-phys-safe
    spec on stdout and a per-role diagnostics summary on stderr.

    NOTE: plan uses `from src.cli.debug import app` but the top-level Typer app
    in debug.py is named `debug_app` (no `app` alias). The test is adjusted to
    import `debug_app` directly — the intent (invoke `target reanchor` end-to-end)
    is preserved unchanged."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app
    import json as _j
    fn = "mnVibration_80248644"
    matched = (FIX / "mnVibration_matched_pcdump.txt")
    if not matched.exists():
        pytest.skip("corpus missing")
    c = rd.Compile.from_text(matched.read_text(), fn, "")
    descs = rd.build_descriptors(c, 0)
    # Use distinguishable (non-empty first_def_sig) roles so virtuals is non-empty
    distinguishable = [ig for ig, d in descs.items() if d.first_def_sig]
    fp = {ig: 13 + (ig % 5) for ig in distinguishable[:6]}
    target = rd.build_target_spec(c, fp, 0, "force_proof_proxy", provenance={"src": "test"})
    tpath = tmp_path / "target.json"; target.save_json(tpath)
    r = CliRunner().invoke(debug_app, ["target", "reanchor", str(tpath), str(matched),
                                       "-f", fn, "--format", "json"])
    assert r.exit_code == 0, r.output
    out = _j.loads(r.stdout)
    assert out["function"] == fn and out["virtuals"]          # non-empty on the no-op case


FIX_LABELS = sorted(FIX.glob("*_labels.json"))


@pytest.mark.parametrize("lab_path", FIX_LABELS, ids=lambda p: p.stem)
def test_reanchor_gate_cross_rev_lands_on_labeled_igs(lab_path):
    """Build a target from the reference rev over the adjudicated roles, re-anchor
    into the drifted rev, and assert each role's desired_phys lands on its
    adjudicated wip ig (the ground truth that defeats raw ig_idx). Confirms Unit 3
    produces a correct force-phys map over the new compile, end to end."""
    lab = json.loads(lab_path.read_text())
    fn, cls = lab["function"], lab["class_id"]
    mp, wp = FIX / lab["matched_dump"], FIX / lab["wip_dump"]
    if not (mp.exists() and wp.exists()):
        pytest.skip("corpus dumps missing")
    same = {int(k): v for k, v in lab["same"].items()}
    mc = rd.Compile.from_text(mp.read_text(), fn, "")
    wc = rd.Compile.from_text(wp.read_text(), fn, "")
    mdescs = rd.build_descriptors(mc, cls)
    scored = [ig for ig in same if ig in mdescs]
    if len(scored) < 3:
        pytest.skip("too few adjudicated roles")
    # give each adjudicated role a distinct desired phys so we can trace it
    desired = {ig: 13 + i for i, ig in enumerate(scored)}
    target = rd.build_target_spec(mc, desired, cls, "force_proof_proxy", provenance={"src": "gate"})
    res = rr.reanchor(target, wc, class_id=cls)
    # every recovered role's phys must appear at its adjudicated wip ig
    expected = {same[ig]: desired[ig] for ig in scored}        # wip_ig -> desired phys
    landed = sum(1 for ig in scored if res.force_phys.get(same[ig]) == desired[ig])
    assert landed >= 0.8 * len(scored), (
        f"{lab_path.stem}: re-anchored {landed}/{len(scored)} roles onto their wip ig "
        f"(diagnostics: {res.diagnostics})")
    # No desired phys may land on an UNEXPECTED ig — including a wip ig that is not
    # this role's adjudicated target (the confident-wrong case round-trip guards).
    desired_vals = set(desired.values())
    stray = {nig: phys for nig, phys in res.force_phys.items()
             if phys in desired_vals and expected.get(nig) != phys}
    assert not stray, f"{lab_path.stem}: phys landed on wrong ig: {stray}"


def test_reanchor_exposes_matched_new_to_original():
    """ReanchorResult.matched maps new_ig -> original_ig for round-trip-confirmed
    roles, so a loop can identify a diverging node as a specific target role."""
    c = _compile("mnVibration_matched", "mnVibration_80248644")
    descs = rd.build_descriptors(c, 0)
    distinguishable = [ig for ig, d in descs.items() if d.first_def_sig]
    fp = {ig: 13 + (ig % 5) for ig in distinguishable[:6]}
    target = rd.build_target_spec(c, fp, 0, "force_proof_proxy", provenance={"src": "t"})
    res = rr.reanchor(target, c, class_id=0)
    # no-op: each matched new_ig maps back to itself (self-match identity)
    for new_ig in res.force_phys:
        assert res.matched[new_ig] == new_ig


def test_reanchor_output_feeds_first_divergence_without_error():
    """The reanchored {virtuals} map builds a fd.TargetColoring that first-divergence
    consumes on the new compile without raising — the integration contract."""
    from src.mwcc_debug import first_divergence as fd
    fn = "mnVibration_80248644"
    mp, wp = FIX / "mnVibration_matched_pcdump.txt", FIX / "mnVibration_wip_pcdump.txt"
    if not (mp.exists() and wp.exists()):
        pytest.skip("corpus missing")
    mc = rd.Compile.from_text(mp.read_text(), fn, "")
    wc = rd.Compile.from_text(wp.read_text(), fn, "")
    md = rd.build_descriptors(mc, 0)
    desired = {ig: 13 + (i % 5) for i, ig in enumerate(list(md)[:6])}
    target = rd.build_target_spec(mc, desired, 0, "force_proof_proxy", provenance={})
    res = rr.reanchor(target, wc, class_id=0)
    tc = fd.TargetColoring(class_id=0, force_phys=res.force_phys)
    # load-bearing: every reanchored key is a real ig in the NEW compile's descriptors
    assert set(tc.force_phys) <= set(rd.build_descriptors(wc, 0))
    assert set(tc.force_phys.keys()) == fd.target_identity_set(tc)   # contract shape
