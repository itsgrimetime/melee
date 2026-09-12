from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.gate import (
    GateOutcome, classify_fidelity, ig_structurally_equal,
    re_extract_and_classify,
)


def _ig(extra_node=False):
    nodes = {
        41: IGNode(41, {42}, {}, 1, False, 30),
        42: IGNode(42, {41}, {}, 1, False, 29),
    }
    order = [41, 42]
    if extra_node:
        nodes[99] = IGNode(99, {41}, {}, 1, False, 27)
        nodes[41].neighbors = {42, 99}
        order = [41, 99, 42]
    return IG(class_id=0, select_order=order, nodes=nodes,
              decision_igs=set(nodes))


def test_structural_equality_detects_identity_and_difference():
    assert ig_structurally_equal(_ig(), _ig()) is True
    assert ig_structurally_equal(_ig(), _ig(extra_node=True)) is False


def test_confirmed_when_present_and_assignments_match():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={41: 30, 99: 27}, actual={41: 30, 99: 27},
        phys_target={99: 27}, no_op=False)
    assert out.classification == "surrogate-confirmed" and out.is_win is True


def test_perfectly_predicted_real_landing_is_not_noop():
    # codex major 9: prediction equality must NOT imply no-op. A real landing
    # whose prediction matches exactly is CONFIRMED (no_op comes from the
    # STRUCTURAL IG comparison, which is False here).
    base, patched = _ig(), _ig(extra_node=True)
    assert ig_structurally_equal(patched, base) is False
    out = classify_fidelity(
        new_ig=99, perturbation_present=(99 in patched.nodes), g1_rate=1.0,
        predicted={99: 27}, actual={99: 27}, phys_target={99: 27},
        no_op=ig_structurally_equal(patched, base))
    assert out.classification == "surrogate-confirmed"


def test_fidelity_miss_present_but_differs_is_model_gap():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={99: 27}, actual={99: 26},
        phys_target={99: 27}, no_op=False)
    assert out.classification == "fidelity-miss"
    assert out.is_win is False and out.model_gap is True


def test_realization_miss_when_perturbation_absent():
    out = classify_fidelity(
        new_ig=99, perturbation_present=False, g1_rate=1.0,
        predicted={99: 27}, actual={}, phys_target={99: 27}, no_op=False)
    assert out.classification == "realization-miss" and out.is_win is False


def test_no_op_is_unattributed_never_a_win():
    out = classify_fidelity(
        new_ig=99, perturbation_present=False, g1_rate=1.0,
        predicted={}, actual={}, phys_target={99: 27}, no_op=True)
    assert out.classification == "UNATTRIBUTED" and out.is_win is False


def test_g1_broken_voids_prediction():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=0.8,
        predicted={99: 27}, actual={99: 27}, phys_target={99: 27}, no_op=False)
    assert out.classification == "g1-broken" and out.is_win is False


# ----------------------------------------------------------------------------
# Blocker-2 residual (binding for T11/T12): the helper must EXPOSE the
# per-contested-register predicted-vs-actual comparison ("present + matches
# target"), not merely a win/no-win boolean. T11's proposal-confirmation-rate
# counts ONLY fixtures whose every contested register matches, so it needs the
# structured per-register result off GateOutcome.
# ----------------------------------------------------------------------------

def test_confirm_exposes_per_register_comparison_all_match():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={41: 30, 99: 27}, actual={41: 30, 99: 27},
        phys_target={41: 30, 99: 27}, no_op=False)
    assert out.classification == "surrogate-confirmed"
    # register_match maps EVERY contested register to (predicted, actual, ok).
    assert out.register_match == {41: (30, 30, True), 99: (27, 27, True)}
    assert out.all_match is True


def test_fidelity_miss_exposes_which_register_diverged():
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={41: 30, 99: 27}, actual={41: 30, 99: 26},
        phys_target={41: 30, 99: 27}, no_op=False)
    assert out.classification == "fidelity-miss"
    # The matching register is still reported ok; the diverged one is False with
    # the actual landing recorded as the counterexample datum.
    assert out.register_match == {41: (30, 30, True), 99: (27, 26, False)}
    assert out.all_match is False


def test_fidelity_miss_records_target_miss_even_when_predicted_equals_actual():
    # Deviation from the plan's verbatim `diverged` filter (predicted != actual):
    # the §3 confirm gate is actual-vs-TARGET, so a register the surrogate
    # predicted correctly but that LANDED off-target (predicted == actual, both
    # != target) is still the cause of the miss and MUST surface. register_match
    # keys `ok` off actual-vs-target, so this register is reported False and the
    # outcome is fidelity-miss with a non-empty divergence detail.
    out = classify_fidelity(
        new_ig=99, perturbation_present=True, g1_rate=1.0,
        predicted={99: 26}, actual={99: 26},
        phys_target={99: 27}, no_op=False)
    assert out.classification == "fidelity-miss" and out.all_match is False
    assert out.register_match == {99: (26, 26, False)}
    assert "99" in out.detail  # the off-target register is named, not hidden


def test_re_extract_from_frozen_artifact_confirms_without_mwcc():
    # Blocker-2: T11 drives this on a FROZEN post-IG artifact (the dump TEXT
    # read off disk) with NO mwcc invocation. The patched dump adds ig 99 at
    # the CONTENDED physical r27 (all volatiles + r31..r28 are blocked, so the
    # dispense rule walks down to r27). predict_assignments over the loaded IG
    # must reproduce the target, and the helper confirms on the full
    # predicted-vs-actual check (not mere node presence).
    frozen_dump = _PATCHED_PCDUMP
    base = _baseline_ig_for_frozen()
    out = re_extract_and_classify(
        patched_pcdump_text=frozen_dump, function="fn_frozen", class_id=0,
        new_ig=99, phys_target={99: 27},
        predicted_assignments={99: 27}, baseline_ig=base)
    assert out.classification == "surrogate-confirmed" and out.is_win is True
    assert out.register_match[99] == (27, 27, True)


def test_re_extract_realization_miss_when_no_colorgraph():
    out = re_extract_and_classify(
        patched_pcdump_text="(no colorgraph here)", function="fn_frozen",
        class_id=0, new_ig=99, phys_target={99: 27},
        predicted_assignments={99: 27}, baseline_ig=_baseline_ig_for_frozen())
    assert out.classification == "realization-miss" and out.is_win is False


def _baseline_ig_for_frozen():
    # Baseline (pre-perturbation): node 41 only, a low volatile (r3); no node 99
    # and no r3..r26 wall yet. Structurally DIFFERENT from the patched IG below
    # (different node set + 41's neighbor set), so no_op is False there.
    nodes = {41: IGNode(41, set(), {}, 1, False, 3)}
    return IG(class_id=0, select_order=[41], nodes=nodes, decision_igs={41})


# A minimal but REAL hook-events COLORGRAPH dump in the format
# colorgraph_parser.parse_hook_events actually consumes (verified against
# _ITER_RE + _INTERFERERS_RE + the post-header skipped column row). The added
# virtual 99 interferes with EVERY GPR volatile {0,3..12} plus callee-saves
# r31/r30/r29/r28, so under the dispense rule SELECT walks past all volatiles
# and the fresh callee-saves r31..r28 to land it at r27 — a CONTENDED physical.
# Node 41 is a pre-existing low node that does NOT interfere with 99, so it stays
# at r0 and the target {99: 27} is internally consistent (G1 = 100%). Expected
# regs are NOT copied from narrative: the test below re-derives them by running
# predict_assignments over the loaded IG (the T2-review binding).
def _decision_block(iter_idx, ig_idx, assigned, *interferers):
    # decision row: iter ig_idx r<reg> degree arraySize 0xflags
    n = len(interferers)
    row = f"  {iter_idx} {ig_idx} r{assigned} {n} {n} 0x0"
    interf = "    interferers: " + " ".join(
        f"{i}=r{r}" for i, r in interferers)
    return [row, interf]


# Block every volatile {0,3..12} and the four fresh callee-saves above r27.
_WALL = [(r, r) for r in (0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 31, 30, 29, 28)]

_PATCHED_PCDUMP = "\n".join([
    "Starting function fn_frozen",
    "COLORGRAPH DECISIONS (class=0, result=0, n_nodes=2)",
    "  iter ig_idx reg degree arraySize flags",  # skipped column-header row
    *_decision_block(0, 41, 0),
    *_decision_block(1, 99, 27, *_WALL),
])
