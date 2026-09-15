import pathlib, pytest
from src.mwcc_debug import role_descriptor as rd
from src.mwcc_debug import role_matcher as rm

FIX = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"
CANARIES = ["gm_80173EEC", "lbDvd_80018A2C", "fn_80247510"]

def _compile(fn):
    p = FIX / f"{fn}_pcdump.txt"
    if not p.exists():
        pytest.skip(f"{fn} fixture missing")
    return rd.Compile.from_text(p.read_text(), fn, source="")

@pytest.mark.parametrize("fn", CANARIES)
def test_gate1a_self_match_is_perfect_identity(fn):
    """A compile matched against ITSELF must map every class-0 role to its own ig
    (correct identity). A node with an identical sibling is honestly AMBIGUOUS
    (it ties its twin) yet still correctly self-identified, so both MATCHED and
    AMBIGUOUS pass. The real failures this floor catches: a node mapped to a
    DIFFERENT ig, or lost (GONE / SPLIT / NON_COMPARABLE)."""
    c = _compile(fn)
    descs = rd.build_descriptors(c, class_id=0)
    if len(descs) < 3:
        pytest.skip(f"{fn}: too few class-0 decision nodes")
    out = rm.match_roles(descs, descs)
    ok_status = (rm.MatchStatus.MATCHED, rm.MatchStatus.AMBIGUOUS)
    wrong = {ig: (m.status.value, m.new_ig) for ig, m in out.items()
             if not (m.new_ig == ig and m.status in ok_status)}
    assert not wrong, f"self-match lost/misidentified a node for {fn}: {wrong}"


import json
FIX_RI = pathlib.Path(__file__).parent / "fixtures" / "role_identity"
LABEL_FILES = sorted(FIX_RI.glob("*_labels.json"))


def _load_corpus(lab_path):
    """Load one labels.json into (lab, ref_descs, new_descs, same, scored).

    `same` maps an adjudicated reference-rev ig to its drifted-rev counterpart;
    `scored` is the subset present in the reference descriptors. The reference
    rev is the higher-% / anchor compile (key `matched_dump`), the drifted rev
    is `wip_dump` — true for mnVibration's 100% anchor and for the sub-100%
    auto-adjudicated functions alike."""
    lab = json.loads(lab_path.read_text())
    matched, wip = FIX_RI / lab["matched_dump"], FIX_RI / lab["wip_dump"]
    if not (matched.exists() and wip.exists()):
        pytest.skip(f"corpus dumps missing for {lab_path.name}")
    fn, cls = lab["function"], lab["class_id"]
    ref = rd.build_descriptors(rd.Compile.from_text(matched.read_text(), fn, ""), cls)
    new = rd.build_descriptors(rd.Compile.from_text(wip.read_text(), fn, ""), cls)
    same = {int(k): v for k, v in lab["same"].items()}
    scored = [ig for ig in same if ig in ref]
    return lab, ref, new, same, scored


@pytest.mark.parametrize("lab_path", LABEL_FILES, ids=lambda p: p.stem)
def test_gate1b_matcher_recovers_drifted_roles_beating_raw_ig(lab_path):
    """Cross-compile (Gate 1b): re-anchor each adjudicated reference-rev role into
    the drifted rev. The matcher must recover the source-grounded roles that raw
    ig_idx lost, with no confident-wrong matches. Runs over every *_labels.json
    in the corpus — mnVibration's hand-adjudicated mix (incl. use-site-recovered
    generic roles) plus the auto unique-first-def sets for the other functions."""
    lab, ref, new, same, scored = _load_corpus(lab_path)
    if len(scored) < 3:
        pytest.skip(f"{lab_path.name}: too few adjudicated roles")
    out = rm.match_roles({ig: ref[ig] for ig in scored}, new)

    decisive = correct = 0
    for ig in scored:
        m = out[ig]
        if m.status == rm.MatchStatus.MATCHED:
            decisive += 1
            correct += int(m.new_ig == same[ig])
    precision = correct / decisive if decisive else 0.0
    raw_ig_correct = sum(1 for ig in scored if same[ig] == ig)
    drifted = sum(1 for ig in scored if same[ig] != ig)

    assert precision >= 0.9, \
        f"{lab_path.stem}: precision {precision} (correct={correct}, decisive={decisive})"
    assert correct >= 0.8 * len(scored), \
        f"{lab_path.stem}: recovered only {correct}/{len(scored)} source-grounded roles"
    if drifted:                                    # the roles raw ig_idx gets wrong
        assert correct > raw_ig_correct, \
            f"{lab_path.stem}: correct {correct} did not beat raw-ig {raw_ig_correct}"


@pytest.mark.parametrize("lab_path", LABEL_FILES, ids=lambda p: p.stem)
def test_gate1c_feature_ablation_reports_contributions(lab_path):
    """Gate 1c: ablate each identity-core feature (weight -> 0) and report how many
    source-grounded recoveries it costs, per corpus function. Confirms the bundle
    — not any single feature — carries identity. Which feature is load-bearing
    depends on the label mix: use_site for mnVibration's generic-first-def roles,
    first_def for the auto unique-first-def sets. Run with -s to see the report."""
    lab, ref, new, same, scored = _load_corpus(lab_path)
    if len(scored) < 3:
        pytest.skip(f"{lab_path.name}: too few adjudicated roles")
    target = {ig: ref[ig] for ig in scored}

    def correct(weights):
        out = rm.match_roles(target, new, weights=weights)
        return sum(1 for ig in scored
                   if out[ig].status == rm.MatchStatus.MATCHED and out[ig].new_ig == same[ig])

    full = correct(rm.DEFAULT_WEIGHTS)
    report = {feat: full - correct({**rm.DEFAULT_WEIGHTS, feat: 0.0})
              for feat in rm.DEFAULT_WEIGHTS}
    print(f"\nGate 1c [{lab_path.stem}]: full={full}/{len(scored)} recovered; "
          f"recoveries lost per ablated feature = {report}")
    assert full >= 0.8 * len(scored), \
        f"{lab_path.stem}: full-weight recovery only {full}/{len(scored)}"


@pytest.mark.parametrize("lab_path", LABEL_FILES, ids=lambda p: p.stem)
def test_gate1d_abstains_on_roles_with_no_counterpart(lab_path):
    """Gate 1d (no false positives): a reference role whose first-def signature is
    unique in the reference compile but ENTIRELY ABSENT from the drifted compile
    has no clean counterpart (the edit removed/changed that operation). The matcher
    must NOT confidently MATCH it to an unrelated node — it must abstain (GONE /
    AMBIGUOUS / SPLIT / NON_COMPARABLE). Phase 3's re-anchoring trusts these non-1:1
    signals; a confident-wrong match would send it chasing a phantom. Skips a
    function when the edit removed no such unique role."""
    import collections
    _lab, ref, new, _same, _scored = _load_corpus(lab_path)
    ref_sig = collections.Counter(x.first_def_sig for x in ref.values())
    new_sigs = {x.first_def_sig for x in new.values()}
    absent = [ig for ig, x in ref.items()
              if x.first_def_sig and ref_sig[x.first_def_sig] == 1
              and x.first_def_sig not in new_sigs]
    if not absent:
        pytest.skip(f"{lab_path.name}: edit removed no unique reference role")
    out = rm.match_roles({ig: ref[ig] for ig in absent}, new)
    bad = {ig: out[ig].new_ig for ig in absent
           if out[ig].status == rm.MatchStatus.MATCHED}
    assert not bad, \
        f"{lab_path.stem}: confident-wrong match on vanished role(s): {bad}"


@pytest.mark.parametrize("lab_path", LABEL_FILES, ids=lambda p: p.stem)
def test_gate1e_use_site_recovers_generic_siblings(lab_path):
    """Gate 1e (use-site stress): GENERIC first-def roles (mr/add/lbz/rlwinm/...)
    that drifted, adjudicated by source-grounded composite def-lineage (the role's
    PRODUCERS chained to a unique anchor) — independent of the matcher's use_site
    (consumers) feature, so non-circular. The matcher must recover them, AND
    recovery must DROP when use_site is ablated, proving use_site is load-bearing
    for roles first-def alone cannot distinguish. Generalizes mnVibration's use_site
    finding across functions/files. Skips functions with no such labels."""
    lab = json.loads(lab_path.read_text())
    uss = {int(k): v for k, v in lab.get("use_site_stress", {}).items()}
    _l, ref, new, _s, _sc = _load_corpus(lab_path)
    scored = [ig for ig in uss if ig in ref]
    if len(scored) < 2:
        pytest.skip(f"{lab_path.name}: no use-site-stress labels")

    def recovered(weights):
        out = rm.match_roles({ig: ref[ig] for ig in scored}, new, weights=weights)
        return sum(1 for ig in scored
                   if out[ig].status == rm.MatchStatus.MATCHED and out[ig].new_ig == uss[ig])

    full = recovered(rm.DEFAULT_WEIGHTS)
    ablated = recovered({**rm.DEFAULT_WEIGHTS, "use_sites": 0.0})
    assert full >= 0.8 * len(scored), \
        f"{lab_path.stem}: recovered only {full}/{len(scored)} generic siblings"
    assert ablated < full, \
        f"{lab_path.stem}: use_site not load-bearing here (full={full}, ablated={ablated})"
