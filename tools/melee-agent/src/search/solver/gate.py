"""§3 fidelity gate — the AFTER-application attribution (the §1.5 remainder).

Outcomes (spec §3):
  surrogate-confirmed : perturbation present + assignments meet the target.
  fidelity-miss       : present + DIFFER -> MODEL GAP datum (NOT "MWCC quirk").
  realization-miss    : perturbation absent -> the C mapping was wrong.
  g1-broken           : G1 < 100% on the patched IG -> prediction void, STOP.
  UNATTRIBUTED        : a no-op perturbation -> never a win (reuses the
                        DirectedMeta.non_actionable discipline).

No-op is detected STRUCTURALLY (spec §3: "one that doesn't change the IG"):
ig_structurally_equal compares select order, node set, and per-node neighbor
sets against the BASELINE IG. Prediction equality is NEVER the no-op signal
(codex major 9 — a real, perfectly-predicted landing must confirm, not void).

classify_fidelity is PURE; re_extract_and_classify is the live seam (fresh
`debug dump local` of the patched source) exercised at the pilots. Because
re_extract_and_classify only PARSES the dump text (`load_ig`) and never invokes
mwcc, T11 drives the SAME helper over FROZEN post-win artifacts (the dump text
read off disk) with no compile — the Blocker-2 residual confirmation path.

Per spec §3 step 3, confirmation is the FULL predicted-vs-actual check on
EVERY contested register, "present + matches target" — not merely node
presence. GateOutcome therefore EXPOSES that comparison via `register_match`
(contested register -> (predicted, actual, ok)) and `all_match`, so T11's
proposal-confirmation-rate metric can count per-register agreement rather than
trusting the boolean alone (codex closure re-review, Blocker-2 residual).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.mwcc_debug.tiebreak import IG


@dataclass
class GateOutcome:
    classification: str   # surrogate-confirmed | fidelity-miss | realization-miss | g1-broken | UNATTRIBUTED
    is_win: bool
    model_gap: bool = False
    detail: str = ""
    # The §3 step-3 predicted-vs-actual comparison, EXPOSED for T11/T12 (the
    # Blocker-2 residual binding): contested register -> (predicted, actual, ok).
    # Empty for outcomes that never reach the comparison (no-op / g1-broken /
    # realization-miss). `all_match` is True iff every contested register's
    # actual landing equals the target (the "present + matches target" gate).
    register_match: dict = field(default_factory=dict)
    all_match: bool = False


def ig_structurally_equal(a: IG, b: IG) -> bool:
    """Structural IG identity: same select order, node set, and neighbor sets."""
    if a is None or b is None:
        return False
    if a.select_order != b.select_order:
        return False
    if set(a.nodes) != set(b.nodes):
        return False
    return all(set(a.nodes[k].neighbors) == set(b.nodes[k].neighbors)
               for k in a.nodes)


def compare_assignments(predicted, actual, phys_target):
    """The §3 step-3 predicted-vs-actual check, EXPOSED so T11 can count
    per-register agreement (not just node presence — Blocker-2 residual).

    For EVERY contested register in `phys_target`, record
    ``(predicted_reg, actual_reg, ok)`` where ``ok`` is whether the ACTUAL
    post-IG landing equals the target. Returns ``(register_match, all_match)``;
    ``all_match`` is the "present + matches target" gate over every contested
    register.
    """
    register_match = {
        k: (predicted.get(k), actual.get(k), actual.get(k) == want)
        for k, want in phys_target.items()
    }
    all_match = all(ok for *_rest, ok in register_match.values())
    return register_match, all_match


def classify_fidelity(*, new_ig, perturbation_present, g1_rate, predicted,
                      actual, phys_target, no_op) -> GateOutcome:
    if no_op:
        return GateOutcome("UNATTRIBUTED", False,
                           detail="no-op perturbation: patched IG structurally "
                                  "identical to baseline")
    if g1_rate < 1.0:
        return GateOutcome("g1-broken", False,
                           detail=f"G1 {g1_rate:.3f} on patched IG; prediction void")
    if not perturbation_present:
        return GateOutcome("realization-miss", False,
                           detail="perturbation absent from re-extracted IG")
    register_match, meets = compare_assignments(predicted, actual, phys_target)
    if meets:
        return GateOutcome("surrogate-confirmed", True,
                           register_match=register_match, all_match=True)
    diverged = {k: (p, a) for k, (p, a, ok) in register_match.items() if not ok}
    return GateOutcome("fidelity-miss", False, model_gap=True,
                       detail=f"present but assignments differ: {diverged}",
                       register_match=register_match, all_match=False)


def re_extract_and_classify(*, patched_pcdump_text, function, class_id, new_ig,
                            phys_target, predicted_assignments, baseline_ig):
    """Live seam: load the patched IG, detect structural no-op vs baseline_ig,
    re-run G1, detect the new node, compare predicted vs actual.

    PARSES the dump text only (`load_ig`) — no mwcc invocation — so T11 drives
    the identical helper over a FROZEN post-win artifact (the Blocker-2 residual
    confirmation: load the frozen IG, run predict_assignments/G1, assert the
    predicted vector matches the actual target on EVERY contested register)."""
    from src.mwcc_debug import tiebreak as tb
    ig = tb.load_ig(patched_pcdump_text, function, class_id=class_id)
    if ig is None:
        return GateOutcome("realization-miss", False,
                           detail="no COLORGRAPH section in patched dump")
    g1 = tb.validate_g1(ig, function)
    return classify_fidelity(
        new_ig=new_ig,
        perturbation_present=new_ig in ig.nodes,
        g1_rate=g1.rate,
        predicted=predicted_assignments,
        actual=tb.predict_assignments(ig),
        phys_target=phys_target,
        no_op=ig_structurally_equal(ig, baseline_ig))
