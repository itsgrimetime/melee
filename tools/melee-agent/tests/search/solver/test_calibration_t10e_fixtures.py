"""T10e — FROZEN real-exemplar whole-solver assertions (mwcc-free, over frozen
artifacts).

For each frozen reject-confirmation fixture (rejected_a = gm_80164504,
flagged_c = ftPp_SpecialS_0_Coll) this reloads the frozen IG (base.pcdump.txt)
+ source-attribution bridge (bridge.json) + phys_target (fixture.json) and
re-runs the PRODUCTION enumerate+filter whole-solver assertion WITHOUT a
compiler — proving the fixture is sound and re-runnable in CI:

  * the production enumeration GENERATES node-add candidates for the class-signal
    target node, and the production passes_1_5_filter DROPS them with the
    fixture's expected token (rejected_a) / QUARANTINES them to the window
    bucket (flagged_c), 0 survivors into full/partial (A1 rev 2 whole-solver);
  * the recompute-equality audit holds (A1 rev 2 §1);
  * the §3 BROKEN-FILTER control breaks the gate (admit-everything -> survivors).

These tests SKIP when a fixture dir is absent (it is frozen by the lock-safe
generator in the campaign worktree; the artifacts + this test live on master).
The frozen `whole_solver` block in fixture.json is the recorded run-5 verdict;
this test RE-DERIVES it from the raw frozen artifacts so a corrupt freeze or a
production-path regression FAILS here, not just a stale recorded number.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mwcc_debug import tiebreak as tb
from src.search.solver import probe
from src.search.solver.calibration_whole_solver import (
    broken_filter_admit_everything,
    recompute_verdict_audit,
    run_whole_solver_node_add,
)
from src.search.solver.enumerate import EnumConfig

CAL = Path(__file__).resolve().parents[2] / "fixtures" / "solver" / "calibration"

REAL_EXEMPLARS = [
    ("reject_a_gm_80164504", "gm_80164504", "rejected_a"),
    ("flag_c_ftPp_SpecialS_0_Coll", "ftPp_SpecialS_0_Coll",
     "flagged_c_exit4_window_order"),
    # Amendment A2: rejected_b on a REAL synthetic-intermediate node (ig55,
    # implicit-temp) in the reused flag_c IG. Closes the dead L2(b) branch + the
    # 5th gate slot.
    ("reject_b_ftPp_SpecialS_0_Coll", "ftPp_SpecialS_0_Coll", "rejected_b"),
]


# ---------------------------------------------------------------------------
# Frozen-bridge reloader: rebuild the minimal probe.py-readable view of an
# explain_virtuals report from its frozen to_dict() JSON (bridge.json). probe.py
# reads ig_idx -> source.name / source.expression / source.first_def.opcode.
# ---------------------------------------------------------------------------
class _FrozenFirstDef:
    def __init__(self, opcode):
        self.opcode = opcode


class _FrozenSource:
    def __init__(self, d):
        self.kind = d.get("kind") if d else None
        self.name = d.get("name") if d else None
        self.expression = d.get("expression") if d else None
        self.source_file = d.get("source_file") if d else None
        self.source_line = d.get("source_line") if d else None
        fd = d.get("first_def") if d else None
        self.first_def = _FrozenFirstDef(fd.get("opcode")) if fd else None


class _FrozenVA:
    def __init__(self, d):
        self.ig_idx = d.get("ig_idx")
        src = d.get("source")
        self.source = _FrozenSource(src) if src is not None else None


class _FrozenReport:
    def __init__(self, bridge_dict):
        self.function = bridge_dict.get("function")
        self.virtuals = tuple(_FrozenVA(v) for v in bridge_dict.get("virtuals", ()))


def _load_fixture(dirname):
    d = CAL / dirname
    fjson = d / "fixture.json"
    pcdump = d / "base.pcdump.txt"
    bridge = d / "bridge.json"
    if not (fjson.exists() and pcdump.exists() and bridge.exists()):
        pytest.skip(f"frozen fixture {dirname} not present (generator runs in "
                    f"the campaign worktree; artifacts land on master)")
    record = json.loads(fjson.read_text())
    ig = tb.load_ig(pcdump.read_text(), record["function"],
                    class_id=record.get("class_id", 0))
    assert ig is not None, f"{dirname}: frozen pcdump has no COLORGRAPH section"
    report = _FrozenReport(json.loads(bridge.read_text()))
    pt = {int(k): int(v) for k, v in record["phys_target"].items()}
    return record, ig, report, pt


@pytest.mark.parametrize("dirname,function,expected", REAL_EXEMPLARS)
def test_frozen_real_exemplar_bridge_reload_matches_recorded_signal(
        dirname, function, expected):
    """The frozen bridge.json reloads to the SAME class signal the freeze
    recorded (the target node's li/lis first-def for rejected_a; the
    window-shift residual for flagged_c)."""
    record, ig, report, pt = _load_fixture(dirname)
    target_ig = record["target_ig"]
    if expected == "rejected_a":
        op = probe.first_def_opcode_of(report, target_ig)
        assert op is not None and op.strip().lower() in ("li", "lis"), (
            f"{function}: frozen target ig={target_ig} first-def {op!r} is not "
            f"a li/lis constant")
    elif expected == "rejected_b":
        # Amendment A2 signal: the target's source is a synthetic intermediate
        # (caller-invisible by KIND) AND runtime (first-def not li/lis).
        src = probe.source_attr_of(report, target_ig)
        assert src is not None, f"{function}: frozen target ig={target_ig} has no source"
        assert probe.caller_visible_source_of(src) is False, (
            f"{function}: frozen target ig={target_ig} source kind "
            f"{getattr(src, 'kind', None)!r} is NOT caller-invisible")
        op = probe.first_def_opcode_of(report, target_ig)
        assert (op or "").strip().lower() not in ("li", "lis"), (
            f"{function}: rejected_b target ig={target_ig} is a li/lis constant "
            f"(would be rejected_a, not rejected_b)")
    else:
        assert probe.is_window_order_residual(ig, pt) is True, (
            f"{function}: frozen phys_target is not a window-shift residual")


@pytest.mark.parametrize("dirname,function,expected", REAL_EXEMPLARS)
def test_frozen_real_exemplar_whole_solver_rejects_or_flags(
        dirname, function, expected):
    """RE-DERIVE the whole-solver verdict from the raw frozen artifacts: the
    production enumerate+filter drops/quarantines the target's node-add
    candidates with the expected token, 0 survivors into full/partial."""
    record, ig, report, pt = _load_fixture(dirname)
    target_ig = record["target_ig"]
    hops = record.get("whole_solver", {}).get("implicated_hops", 1)
    cfg = EnumConfig(implicated_hops=hops)
    window_residual = probe.is_window_order_residual(ig, pt)
    if expected in ("rejected_a", "rejected_b"):
        v = run_whole_solver_node_add(
            ig, pt, target_ig=target_ig, report=report,
            window_residual=window_residual, expected_reject_token=expected,
            config=cfg)
        assert v.candidates_for_target > 0
        assert v.rejected_count == v.candidates_for_target
        assert v.survived_in_full == 0
        assert v.survived_in_partial == 0
        assert v.survived_in_window == 0
        assert v.reject_token == expected
        audit = recompute_verdict_audit(ig, report, target_ig=target_ig,
                                        window_residual=window_residual,
                                        config=cfg)
        assert audit["reasons"] == [expected]
        assert audit["admits"] == 0
    else:
        v = run_whole_solver_node_add(
            ig, pt, target_ig=target_ig, report=report,
            window_residual=window_residual, expected_flag="flagged_c",
            config=cfg)
        assert v.candidates_for_target > 0
        assert v.flagged_count > 0
        assert v.flagged_count == v.survived_in_window
        assert v.survived_in_full == 0
        assert v.survived_in_partial == 0
        assert v.reject_token == "flagged_c"


@pytest.mark.parametrize("dirname,function,expected", REAL_EXEMPLARS)
def test_frozen_real_exemplar_broken_filter_control_breaks_gate(
        dirname, function, expected):
    """A1 rev 2 §3 over the frozen artifacts: an admit-everything filter lets the
    target's candidates survive (rejected_a) / mis-routes them out of the window
    bucket (flagged_c) — the clean gate predicate FAILS, as it must."""
    record, ig, report, pt = _load_fixture(dirname)
    target_ig = record["target_ig"]
    hops = record.get("whole_solver", {}).get("implicated_hops", 1)
    cfg = EnumConfig(implicated_hops=hops)
    window_residual = probe.is_window_order_residual(ig, pt)
    _hard_reject = expected in ("rejected_a", "rejected_b")
    bf = run_whole_solver_node_add(
        ig, pt, target_ig=target_ig, report=report,
        window_residual=window_residual,
        expected_reject_token=(expected if _hard_reject else None),
        expected_flag=(None if _hard_reject else "flagged_c"),
        filter_fn=broken_filter_admit_everything, config=cfg)
    if _hard_reject:
        # The reliable §3 signal: the admit-everything enum filter ADMITS every
        # target candidate (vs 0 under the real filter), so the clean-reject
        # gate predicate ("the production filter rejects every target candidate")
        # FAILS. (Survivors are unreliable: a constant/synthetic node-add is
        # non-productive and leaves no hit even when admitted.)
        assert (bf.target_candidates_admitted_by_enum_filter
                == bf.candidates_for_target > 0)
        # Cross-check the REAL filter rejects them all (admits 0).
        real = run_whole_solver_node_add(
            ig, pt, target_ig=target_ig, report=report,
            window_residual=window_residual,
            expected_reject_token=expected, config=cfg)
        assert real.target_candidates_admitted_by_enum_filter == 0
    else:
        # flag_c: under admit-everything the candidates are NOT quarantined.
        assert bf.survived_in_window != bf.candidates_for_target


def test_frozen_recorded_whole_solver_block_is_consistent():
    """The frozen fixture.json `whole_solver` block (the recorded run-5 verdict)
    must internally agree with its assertions: the gate ok flags True, the
    broken-filter control breaks the gate. (Re-derivation is the other tests;
    this pins the RECORD so a hand-edit of fixture.json is caught.)"""
    any_present = False
    for dirname, _fn, _exp in REAL_EXEMPLARS:
        fjson = CAL / dirname / "fixture.json"
        if not fjson.exists():
            continue
        any_present = True
        ws = json.loads(fjson.read_text()).get("whole_solver", {})
        assert ws.get("whole_solver_reject_assertion_ok") is True, dirname
        assert ws.get("recompute_equality_audit_ok") is True, dirname
        assert ws.get("broken_filter_control", {}).get("breaks_gate") is True, dirname
    if not any_present:
        pytest.skip("no frozen real-exemplar fixtures present")
