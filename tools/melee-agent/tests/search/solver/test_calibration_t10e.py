"""T10e — final reject-confirmation calibration harness (pure-logic unit tests).

These pin the PURE pieces of the whole-solver reject-confirmation harness with
NO compiler in the loop (synthetic IGs + a fake explain_virtuals report), the
same discipline as test_probe / test_validity:

  * the no-oracle ProbeContext derivation (build_probe_ctx_fn reads only raw
    report/IG fields — A1 rev 2 §1);
  * the whole-solver reject: the production enumerate_single GENERATES node-add
    candidates for a target and the production filter DROPS them with the
    expected token, 0 survivors (rejected_a / rejected_b shapes);
  * the flag_c quarantine: candidates are FLAGGED and routed to window_order,
    never full/partial (A1 rev 2 §5 candidate-level quarantine);
  * the BROKEN-FILTER control: an admit-everything stub makes the reject/flag
    assertion FAIL (A1 rev 2 §3 — a filter that can't fail can't pass the gate);
  * the recompute-equality audit (A1 rev 2 §1);
  * paired-trace invariance baseline-vs-planted (A1 rev 2 §4).

The frozen REAL-exemplar assertions (gm_80164504 rejected_a, ftPp_SpecialS_0_Coll
flagged_c) live in test_calibration_t10e_fixtures.py (gated on the frozen dirs).
"""
from __future__ import annotations

from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver import probe
from src.search.solver.calibration_whole_solver import (
    broken_filter_admit_everything,
    build_probe_ctx_fn,
    paired_trace_invariance,
    recompute_verdict_audit,
    run_whole_solver_node_add,
)
from src.search.solver.enumerate import EnumConfig, enumerate_single
from src.search.solver.types import Perturbation, PerturbationKind
from src.search.solver.validity import passes_1_5_filter


# ---------------------------------------------------------------------------
# Fake explain_virtuals report: the FROZEN source-attribution bridge, shaped
# exactly like the real VirtualAttributionReport probe.py reads (ig_idx ->
# source with .name/.expression/.first_def.opcode). No oracle fields.
# ---------------------------------------------------------------------------
class _FakeFirstDef:
    def __init__(self, opcode):
        self.opcode = opcode


class _FakeSource:
    def __init__(self, name=None, expression=None, first_def_opcode=None,
                 kind="local", source_file=None, source_line=None):
        self.kind = kind
        self.name = name
        self.expression = expression
        self.source_file = source_file
        self.source_line = source_line
        self.first_def = (_FakeFirstDef(first_def_opcode)
                          if first_def_opcode is not None else None)


class _FakeVA:
    def __init__(self, ig_idx, source):
        self.ig_idx = ig_idx
        self.source = source


class _FakeReport:
    def __init__(self, by_ig):
        # by_ig: {ig_idx: _FakeSource | None}
        self.virtuals = tuple(_FakeVA(i, s) for i, s in by_ig.items())


def _ig_with(nodes_spec, phys_target_keys):
    """Build a small class=0 GPR IG. nodes_spec: {ig: (neighbors, observed_reg)}."""
    nodes = {i: IGNode(i, set(nb), {}, len(nb), False, reg)
             for i, (nb, reg) in nodes_spec.items()}
    order = sorted(nodes)
    return IG(class_id=0, select_order=order, nodes=nodes,
              decision_igs=set(nodes))


# A small graph: node 38 is a li-constant (rejected_a class), node 40 is a
# runtime caller-visible local (admit class), node 41 is a runtime SYNTHETIC
# intermediate (implicit-temp -> rejected_b class, Amendment A2). phys_target
# contests 38 and 40.
NODES = {
    38: ({40, 41}, 7),     # current r7, target wants r3 (contested)
    40: ({38, 41}, 4),     # runtime local
    41: ({38, 40}, 5),     # runtime implicit-temp (no source variable)
}
PHYS_TARGET = {38: 3, 40: 4}   # 38 off-target (r7->r3), 40 on-target


def _report_rejected_a():
    return _FakeReport({
        38: _FakeSource(kind="first-def", expression="li r38,0",
                        first_def_opcode="li"),                          # const
        40: _FakeSource(kind="local", name="x_spacing",
                        expression="x_spacing"),                         # runtime
        41: _FakeSource(kind="implicit-temp", expression="addi r41,r40,8",
                        first_def_opcode="addi"),
    })


def _report_rejected_b():
    # Amendment A2: the rejected_b class is a runtime SYNTHETIC intermediate WITH
    # a source (the ig55 refreeze shape: implicit-temp addi), NOT source=None.
    # The kind, not name/expression presence, drives caller-invisibility.
    return _FakeReport({
        38: _FakeSource(kind="field-load", expression="lwz r38,8(r3)",
                        first_def_opcode="lwz"),                # caller-visible
        40: _FakeSource(kind="local", name="x_spacing", expression="x_spacing"),
        41: _FakeSource(kind="implicit-temp", expression="addi r41,r40,1",
                        first_def_opcode="addi"),    # synthetic -> rejected_b
    })


# === A1 rev 2 §1: no-oracle ProbeContext derivation ========================
def test_probe_ctx_fn_reads_only_raw_fields_rejected_a():
    ig = _ig_with(NODES, PHYS_TARGET)
    ctx_fn = build_probe_ctx_fn(ig, _report_rejected_a(), window_residual=False)
    p = Perturbation(PerturbationKind.NODE_ADD, target_ig=38, use_set=(40,),
                     new_ig=99, position="after", interfere_original=True)
    ctx = ctx_fn(p)
    # 38's first-def is `li` -> NOT runtime -> the filter rejects_a. (Under
    # Amendment A2 a nameless/lineless li first-def is ALSO caller-invisible, but
    # L2(a) is checked FIRST in passes_1_5_filter, so the verdict is rejected_a.)
    assert ctx.is_runtime_value is False
    assert ctx.caller_visible_source is False
    assert passes_1_5_filter(p, ctx).reason == "rejected_a"


def test_probe_ctx_fn_reads_only_raw_fields_rejected_b():
    ig = _ig_with(NODES, PHYS_TARGET)
    ctx_fn = build_probe_ctx_fn(ig, _report_rejected_b(), window_residual=False)
    p = Perturbation(PerturbationKind.NODE_ADD, target_ig=41, use_set=(40,),
                     new_ig=99, position="after", interfere_original=True)
    ctx = ctx_fn(p)
    # 41 is runtime (implicit-temp addi -> not li/lis) but a SYNTHETIC
    # intermediate (no source variable) -> caller_visible_source False ->
    # rejected_b (Amendment A2: KIND, not source=None).
    assert ctx.is_runtime_value is True
    assert ctx.caller_visible_source is False
    assert passes_1_5_filter(p, ctx).reason == "rejected_b"


# === A1 rev 2 §1: recompute-equality audit =================================
def test_recompute_audit_single_token_rejected_a():
    ig = _ig_with(NODES, PHYS_TARGET)
    audit = recompute_verdict_audit(ig, _report_rejected_a(), target_ig=38,
                                    window_residual=False)
    assert audit["candidates"] > 0
    assert audit["reasons"] == ["rejected_a"]   # exactly one token, no admits
    assert audit["admits"] == 0
    assert audit["flags"] == []


def test_recompute_audit_single_token_rejected_b():
    ig = _ig_with(NODES, PHYS_TARGET)
    audit = recompute_verdict_audit(ig, _report_rejected_b(), target_ig=41,
                                    window_residual=False)
    assert audit["reasons"] == ["rejected_b"]
    assert audit["admits"] == 0


def test_audit_equal_detects_filter_substitution():
    """A1 rev 2 §1: audit_equal compares the production predicate against the
    verdict the ENUMERATION actually applied (filter_fn). Real filter -> equal
    (True); admit-everything substitute -> NOT equal on a rejected candidate
    (False). A tautological self-comparison would be meaningless."""
    ig = _ig_with(NODES, PHYS_TARGET)
    report = _report_rejected_a()
    real = run_whole_solver_node_add(
        ig, PHYS_TARGET, target_ig=38, report=report,
        window_residual=False, expected_reject_token="rejected_a")
    broken = run_whole_solver_node_add(
        ig, PHYS_TARGET, target_ig=38, report=report,
        window_residual=False, expected_reject_token="rejected_a",
        filter_fn=broken_filter_admit_everything)
    assert real.audit_equal is True       # production filter matches itself
    assert broken.audit_equal is False    # admit-everything diverges -> caught


# === whole-solver reject: production enumerate generates + filter drops ====
def test_whole_solver_rejects_constant_node_rejected_a():
    ig = _ig_with(NODES, PHYS_TARGET)
    v = run_whole_solver_node_add(
        ig, PHYS_TARGET, target_ig=38, report=_report_rejected_a(),
        window_residual=False, expected_reject_token="rejected_a")
    assert v.candidates_for_target > 0           # the generator MADE candidates
    assert v.rejected_count == v.candidates_for_target  # ALL rejected_a
    assert v.survived_in_full == 0               # none survived the filter
    assert v.survived_in_partial == 0
    assert v.survived_in_window == 0
    assert v.reject_token == "rejected_a"
    assert v.audit_equal is True


def test_whole_solver_rejects_intra_inline_node_rejected_b():
    ig = _ig_with(NODES, PHYS_TARGET)
    # contest node 41 too, so the generator targets it
    pt = {38: 3, 41: 3}
    v = run_whole_solver_node_add(
        ig, pt, target_ig=41, report=_report_rejected_b(),
        window_residual=False, expected_reject_token="rejected_b")
    assert v.candidates_for_target > 0
    assert v.rejected_count == v.candidates_for_target
    assert v.survived_in_full == 0 and v.survived_in_partial == 0
    assert v.reject_token == "rejected_b"


# === A1 rev 2 §3: BROKEN-FILTER control ====================================
def test_broken_filter_admits_everything_breaks_the_reject():
    """Under an admit-everything filter, the enumeration ADMITS every rejected_a
    target candidate (vs 0 under the real filter). The clean-reject gate
    predicate ("the production filter rejects every target candidate" -> 0
    admitted by the enum filter) therefore FAILS, as A1 rev 2 §3 requires: a
    filter that can't fail can't pass the gate.

    (Survivors are NOT a reliable signal for a CONSTANT node: a li-constant
    node-add is non-productive, so it leaves no hit even when admitted. The
    admitted-by-enum-filter count is the faithful control signal.)"""
    ig = _ig_with(NODES, PHYS_TARGET)
    real = run_whole_solver_node_add(
        ig, PHYS_TARGET, target_ig=38, report=_report_rejected_a(),
        window_residual=False, expected_reject_token="rejected_a")
    broken = run_whole_solver_node_add(
        ig, PHYS_TARGET, target_ig=38, report=_report_rejected_a(),
        window_residual=False, expected_reject_token="rejected_a",
        filter_fn=broken_filter_admit_everything)
    # Real filter: rejects (admits 0). Broken filter: admits ALL.
    assert real.target_candidates_admitted_by_enum_filter == 0
    assert (broken.target_candidates_admitted_by_enum_filter
            == broken.candidates_for_target > 0)
    # The clean-reject gate predicate (production filter rejects every target
    # candidate) holds under the real filter, FAILS under the broken one.
    def _clean_reject_gate(v):
        return v.target_candidates_admitted_by_enum_filter == 0
    assert _clean_reject_gate(real) is True
    assert _clean_reject_gate(broken) is False


# === flag_c candidate-level quarantine (A1 rev 2 §5) =======================
# A window-order residual: every contested node is a callee-save with a uniform
# +1 shift. window_residual=True -> the runtime, caller-visible, surviving copy
# is FLAGGED flagged_c and routed to the window bucket, never full/partial.
WIN_NODES = {
    28: ({27, 29}, 28),    # observed r28, target r27 (callee-save, +1)
    27: ({28}, 27),
    29: ({28}, 29),
}
WIN_TARGET = {28: 27}      # single uniform +1 callee-save shift


def _report_flag_c():
    return _FakeReport({
        28: _FakeSource(name="var", expression="state->x8",
                        first_def_opcode="lwz"),   # runtime, caller-visible
        27: _FakeSource(name="a", expression="a"),
        29: _FakeSource(name="b", expression="b"),
    })


def test_window_residual_signal_is_derived_from_frozen_artifacts():
    ig = _ig_with(WIN_NODES, WIN_TARGET)
    # The production window classifier over the frozen IG + target.
    assert probe.is_window_order_residual(ig, WIN_TARGET) is True


def test_whole_solver_flags_window_order_candidate_flag_c():
    ig = _ig_with(WIN_NODES, WIN_TARGET)
    window_residual = probe.is_window_order_residual(ig, WIN_TARGET)
    v = run_whole_solver_node_add(
        ig, WIN_TARGET, target_ig=28, report=_report_flag_c(),
        window_residual=window_residual, expected_flag="flagged_c")
    assert v.candidates_for_target > 0
    # The all-uses use-set family routes EVERY neighbor -> L1 coalesce-bait ->
    # rejected_survival BEFORE the (c) flag (correct production ordering); the
    # PROPER-SUBSET families are the ones that reach the flag. So flagged_count
    # is the surviving-copy subset, > 0, and every flagged candidate is
    # quarantined to the window bucket (A1 rev 2 §5 candidate-level quarantine).
    assert v.flagged_count > 0
    assert v.flagged_count == v.survived_in_window
    # NONE of the target's candidates reach full/partial — the flag never
    # produces an apply/exit-0 candidate.
    assert v.survived_in_full == 0
    assert v.survived_in_partial == 0
    assert v.reject_token == "flagged_c"


def test_flag_c_broken_filter_control_misroutes_to_full_hits():
    """§3 control for flag_c: admit-everything stops the flag, so the candidates
    are NOT routed to the window bucket. They land in full/partial instead (28 is
    on its target after the perturbation in some family) OR simply are not
    quarantined. Either way `survived_in_window == candidates_for_target` FAILS."""
    ig = _ig_with(WIN_NODES, WIN_TARGET)
    v = run_whole_solver_node_add(
        ig, WIN_TARGET, target_ig=28, report=_report_flag_c(),
        window_residual=True, expected_flag="flagged_c",
        filter_fn=broken_filter_admit_everything)
    assert v.survived_in_window != v.candidates_for_target


# === A1 rev 2 §4: paired-trace invariance ==================================
def _enum(ig, pt, report, *, extra_node_add=None):
    """Run the production single enumeration; optionally inject one EXTRA
    node-add candidate (the plant) by widening phys_target's implicated set is
    not how the plant injects — instead we compare two runs whose IGs differ
    only by the plant target being contested or not."""
    cfg = EnumConfig()
    ctx_fn = build_probe_ctx_fn(ig, report, window_residual=False)
    return enumerate_single(ig, pt, config=cfg, filter_fn=passes_1_5_filter,
                            probe_ctx_fn=ctx_fn, kinds=("node-add",))


def test_paired_trace_invariance_plant_does_not_perturb_baseline():
    """Baseline contests {40}; the 'planted' run ALSO contests the plant target
    38 (a li-constant -> rejected, generates 0 survivors). The non-plant
    candidate identities + outcomes, truncation, and edge/order evals must be
    UNCHANGED; node-add evals may grow by the plant's own."""
    ig = _ig_with(NODES, PHYS_TARGET)
    report = _report_rejected_a()
    baseline = _enum(ig, {40: 4}, report)                 # only 40 contested
    planted = _enum(ig, {40: 4, 38: 3}, report)           # + plant target 38
    res = paired_trace_invariance(baseline, planted, plant_target_ig=38)
    assert res.non_plant_identities_unchanged is True
    assert res.non_plant_outcomes_unchanged is True
    assert res.truncated_unchanged is True
    assert res.per_kind_evals_unchanged_modulo_plant is True
    assert res.invariant is True


def _result_with(full=(), partial=(), window=(), *, truncated=False,
                 evals=None):
    """Construct an EnumResult directly (pure comparator inputs). Each hit spec
    is (target_ig, use_set, targets_met)."""
    def _mk(specs):
        out = []
        for tig, use_set, met in specs:
            out.append({
                "perturbation": Perturbation(
                    PerturbationKind.NODE_ADD, target_ig=tig, use_set=use_set,
                    new_ig=10_000 + len(out), position="after",
                    interfere_original=True),
                "targets_met": met, "delta": {}, "actionable": False})
        return out
    from src.search.solver.enumerate import EnumResult
    return EnumResult(
        full_hits=_mk(full), partial_hits=_mk(partial),
        window_order_hits=_mk(window),
        filter_counts={}, evals_per_kind=(evals or {"node-add": 5, "edge": 0,
                                                     "order": 0}),
        truncated=truncated, last_kind="node-add")


def test_paired_trace_invariance_passes_when_only_plant_differs():
    """The plant (target 38) appears ONLY in the planted run; every non-plant
    candidate identity + outcome, the winning alias (target 40) identity + rank,
    truncation, and edge/order evals are identical -> invariant True
    (A1 rev 2 §4). node-add evals grow by the plant's own."""
    baseline = _result_with(
        full=[(40, (41,), 1)], partial=[(41, (40,), 1)],
        evals={"node-add": 5, "edge": 3, "order": 2})
    planted = _result_with(
        full=[(40, (41,), 1), (38, (40,), 1)],     # + the plant (38)
        partial=[(41, (40,), 1)],
        evals={"node-add": 7, "edge": 3, "order": 2})   # +2 node-add (plant)
    res = paired_trace_invariance(baseline, planted, plant_target_ig=38,
                                  winning_alias_target_ig=40)
    assert res.non_plant_identities_unchanged is True
    assert res.non_plant_outcomes_unchanged is True
    assert res.winning_alias_identity_unchanged is True
    assert res.winning_alias_rank_unchanged is True
    assert res.truncated_unchanged is True
    assert res.per_kind_evals_unchanged_modulo_plant is True
    assert res.invariant is True


def test_paired_trace_detects_a_perturbing_plant_outcome():
    """A plant that CHANGES a non-plant candidate's OUTCOME must be caught: the
    node-41 partial hit's targets_met differs between runs -> not invariant."""
    baseline = _result_with(partial=[(41, (40,), 1)])
    planted = _result_with(partial=[(41, (40,), 2)],      # outcome changed
                           full=[(38, (40,), 1)])          # plant present
    res = paired_trace_invariance(baseline, planted, plant_target_ig=38)
    assert res.non_plant_outcomes_unchanged is False
    assert res.invariant is False


def test_paired_trace_detects_winning_alias_rank_change():
    """§4 pins the winning-alias RANK: if the plant displaces the alias in the
    ranked full-hit list, the rank guard must fire."""
    baseline = _result_with(full=[(40, (41,), 1), (50, (51,), 1)])
    # Plant 38 inserted BEFORE the alias 40 in the full-hit order -> alias rank
    # shifts from 0 to 1 (the comparator excludes the plant, so this models a
    # mis-ordered planted list where a NON-plant entry moved).
    planted = _result_with(full=[(50, (51,), 1), (40, (41,), 1)])   # 50,40 swapped
    res = paired_trace_invariance(baseline, planted, plant_target_ig=38,
                                  winning_alias_target_ig=40)
    assert res.winning_alias_rank_unchanged is False
    assert res.invariant is False


def test_paired_trace_detects_truncation_change():
    """§4 also pins enumeration_truncated: a planted run that flips truncation
    (e.g. the plant pushed evals over a floor) must be caught."""
    baseline = _result_with(partial=[(41, (40,), 1)], truncated=False)
    planted = _result_with(partial=[(41, (40,), 1)], truncated=True)
    res = paired_trace_invariance(baseline, planted, plant_target_ig=38)
    assert res.truncated_unchanged is False
    assert res.invariant is False


def test_paired_trace_detects_edge_order_eval_change():
    """§4: edge/order eval counts must be IDENTICAL (the plant only touches the
    node-add bucket). A changed edge eval count -> not invariant."""
    baseline = _result_with(partial=[(41, (40,), 1)],
                            evals={"node-add": 5, "edge": 3, "order": 2})
    planted = _result_with(partial=[(41, (40,), 1)],
                           evals={"node-add": 5, "edge": 4, "order": 2})
    res = paired_trace_invariance(baseline, planted, plant_target_ig=38)
    assert res.per_kind_evals_unchanged_modulo_plant is False
    assert res.invariant is False
