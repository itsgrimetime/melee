import pathlib
import pytest
from src.mwcc_debug import role_descriptor as rd

FIX = pathlib.Path(__file__).parent / "fixtures" / "mwcc_debug"


def _has(fn):
    return (FIX / f"{fn}_pcdump.txt").exists()


def test_compile_from_text_exposes_fev_fn_source():
    if not _has("lbDvd_80018A2C"):
        pytest.skip("fixture missing")
    text = (FIX / "lbDvd_80018A2C_pcdump.txt").read_text()
    c = rd.Compile.from_text(text, "lbDvd_80018A2C", source="")
    assert c.name == "lbDvd_80018A2C"
    assert c.fev is not None and c.fev.name == "lbDvd_80018A2C"
    assert c.fn is not None and c.fn.name == "lbDvd_80018A2C"
    assert c.fn.last_precolor_pass() is not None  # parser.Function has the pre-pass


def test_normalize_first_def_strips_volatile_regs_keeps_structure():
    from src.mwcc_debug.symbol_bridge import FirstDef
    # raw virtual numbers differ across compiles; offset/opcode are stable
    a = FirstDef(block_idx=3, opcode="lwz", operands="r62, 0x2C(r34)", annotations=[], regs=[])
    b = FirstDef(block_idx=9, opcode="lwz", operands="r88, 0x2C(r91)", annotations=[], regs=[])
    assert rd.normalize_first_def(a) == rd.normalize_first_def(b)
    assert "0x2c" in rd.normalize_first_def(a)          # offset kept
    assert "lwz" in rd.normalize_first_def(a)           # opcode kept
    assert rd.normalize_first_def(None) == ""
    # different opcode/offset must NOT collide
    c = FirstDef(block_idx=3, opcode="lwz", operands="r62, 0x30(r34)", annotations=[], regs=[])
    assert rd.normalize_first_def(a) != rd.normalize_first_def(c)


def test_build_descriptors_splits_identity_core_from_state():
    if not _has("lbDvd_80018A2C"):
        pytest.skip("fixture missing")
    text = (FIX / "lbDvd_80018A2C_pcdump.txt").read_text()
    c = rd.Compile.from_text(text, "lbDvd_80018A2C", source="")
    descs = rd.build_descriptors(c, class_id=0)
    assert descs, "no class-0 descriptors built"
    d = next(iter(descs.values()))
    assert isinstance(d.first_def_sig, str)
    assert isinstance(d.use_site_multiset, tuple)
    assert isinstance(d.is_param, bool)
    assert isinstance(d.use_count, int)
    assert isinstance(d.live_range, tuple) and len(d.live_range) == 2
    assert all(ig >= 0 for ig in descs)


def test_build_descriptors_uses_fpr_facts_for_fpr_class():
    # fn_80247510 has real class-1 (FPR) decisions and fNN pre-coloring
    # definitions. The descriptor bridge must read those fNN facts rather than
    # rejecting class 1 or accidentally reusing same-numbered GPR data.
    if not _has("fn_80247510"):
        pytest.skip("fixture missing")
    c = rd.Compile.from_text((FIX / "fn_80247510_pcdump.txt").read_text(),
                             "fn_80247510", source="")
    descs = rd.build_descriptors(c, class_id=1)

    assert descs
    assert 42 in descs
    assert descs[42].first_def_sig.startswith("lfd f#")
    assert descs[42].use_count > 0
    assert descs[42].live_range != (-1, -1)
    assert rd.build_descriptors(c, class_id=0)   # class 0 (GPR) still works


def test_target_spec_roundtrips_through_json(tmp_path):
    if not _has("lbDvd_80018A2C"):
        pytest.skip("fixture missing")
    text = (FIX / "lbDvd_80018A2C_pcdump.txt").read_text()
    c = rd.Compile.from_text(text, "lbDvd_80018A2C", source="")
    spec = rd.build_target_spec(
        c, force_phys={44: 10, 46: 12}, class_id=0,
        target_kind="force_proof_proxy",
        provenance={"source_commit": "deadbeef", "dump_sha256": "abc"})
    assert spec.target_kind == "force_proof_proxy"
    assert {r.original_ig for r in spec.roles} == {44, 46}
    r46 = next(r for r in spec.roles if r.original_ig == 46)
    assert r46.desired_phys == 12 and r46.class_id == 0
    assert r46.role_order_rank is not None      # 46 is a decision node -> has a rank
    p = tmp_path / "spec.json"
    spec.save_json(p)
    back = rd.TargetSpec.load_json(p)
    assert back.target_kind == spec.target_kind
    assert {r.original_ig for r in back.roles} == {44, 46}
    assert back.roles[0].descriptor.first_def_sig == \
        next(r for r in spec.roles if r.original_ig == back.roles[0].original_ig).descriptor.first_def_sig


def test_target_spec_roundtrips_structural_role_with_none_descriptor(tmp_path):
    # a coalesced/spilled target role has descriptor=None and rank=None;
    # it must persist + reload without crashing.
    spec = rd.TargetSpec(
        function="f", target_kind="force_proof_proxy", target_coverage=0.0,
        causal_closure=False, provenance={"source_commit": "x", "dump_sha256": "y"},
        roles=[rd.TargetRoleSpec(original_ig=99, desired_phys=28, class_id=0,
                                 descriptor=None, role_order_rank=None)])
    p = tmp_path / "spec.json"
    spec.save_json(p)
    back = rd.TargetSpec.load_json(p)
    assert len(back.roles) == 1
    assert back.roles[0].original_ig == 99
    assert back.roles[0].descriptor is None
    assert back.roles[0].role_order_rank is None
