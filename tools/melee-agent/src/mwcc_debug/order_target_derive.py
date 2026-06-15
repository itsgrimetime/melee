"""derive_order_target — the §4.2 derivation/classification pipeline as a PURE
function over already-collected tool outputs.

The CLI (debug target order-target) collects the tool outputs (checkdiff,
force-phys-from-diff, the minimal forcing-set search, two forced dump
readbacks, baseline self-reanchor) and hands them here as a DeriveInputs. This
function applies the ordered classification (each failure mode is a named
routing, never an error) and returns an OrderTarget. Keeping it pure makes the
partition logic unit-testable without any mwcc compilation.

Ordering matters and matches §4.2:
  1. register-only precondition (a structural diff is NOT in this pool -> raise)
  2. phys conflict -> not_order_class (before any forced compile)
  3. minimal-set search exhausted under the 64-cap -> force_cap_blocked
     (the collector sets force_cap_exceeded ONLY after probing the <=64 window;
      a >64 chosen list is a contract guard -> also force_cap_blocked)
  4a. forced ig absent OR at the wrong position -> unstable_target
      (position-exact: the ig at 0-based list index i must sit at DECISIONS
       position i; present-but-elsewhere is a silent misapply)
  4b. forced build did not eliminate the class residual -> not_order_class
  5. forced ig-set != baseline ig-set -> unstable_target
  6. < 2 self-reanchored roles -> unanchorable
  7. derive-twice DECISIONS hashes differ -> unstable_target
  else -> directed

ROUTING KEYS ON THE FORCED-ORDER BYTE-VERDICT, NEVER ON ATTRIBUTION.
class_evidence strings are leads to confirm, not proofs (the 8024227C round-1
"arg-home coalesce" attribution was retracted by ORACLE ROUND 2 while the
not_order_class routing stood; verify:
  git show 8bd6f8648:CAMPAIGN-STATE-D1COMPLETION.md | grep -n -A4 'ORACLE ROUND 2').
"""

from __future__ import annotations

from dataclasses import dataclass

from src.search.directed.order_target import FORCE_CAP, OrderTarget, Routing

# checkdiff classification primaries with matching opcode sequences (the
# register-only / FULLNORM-0 admission set). backend-ceiling's coloring-rotation
# subclass is exactly this pool's signature; the step-4 class gate is the
# outcome-verified arbiter for anything mis-admitted.
#
# normalized-structural-match (#576 truth-gate vocabulary: the "zero structural
# diff demotion" — the normalized structural diff is ZERO after masking
# registers/immediates/labels/relocations) is the FULLNORM-0 pure-coloring
# signature itself, the pool's STRONGEST admission signal. The original
# two-primary set predated the #576 vocabulary and mis-rejected it (T6 round-1
# finding: fn_803ACD58 base at 98.94% with a structurally-zero masked diff —
# a pure register residual — was routed out at Step 1).
REGISTER_ONLY_PRIMARIES = {
    "operand-register-or-offset",
    "backend-ceiling",
    "normalized-structural-match",
}


@dataclass
class DeriveInputs:
    """Collected tool outputs for one function's derivation."""

    function: str
    unit: str
    class_id: int
    checkdiff_primary: str                 # classification["primary"] from checkdiff JSON
    phys_target: dict                      # {orig_ig: desired_phys}
    phys_conflicts: list                   # force-phys-from-diff conflicts
    force_iter_first: list                 # the CHOSEN (<=64) forcing list
    applied_positions: dict                # {forced_ig: 0-based DECISIONS position}
    forced_class_clean: bool               # union probe byte-eliminated the class residual
    forced_ranks: dict                     # {ig: 1-based rank} from the FORCED DECISIONS
    baseline_ig_set: set
    forced_ig_set: set
    self_reanchored_roles: set             # baseline round-trip-MATCHED roles
    unscored_roles: list                   # [{ig, reason}]
    forced_decisions_sha256: list          # two independent forced readbacks
    baseline_source_sha256: str
    baseline_pcdump_sha256: str
    # B1: set by the collector's minimal-set search ONLY when the anchor list
    # exceeded 64 AND the <=64 window did not eliminate the class residual.
    force_cap_exceeded: bool = False
    # #619: the COMPUTED direct-evidence register-only verdict (win_fixture
    # is_register_only_admission). Set ONLY by the solve-coloring admission path
    # (it passes the direct-evidence gate); None for the order-target derivation
    # path, whose Step-1 precondition keys on the label and never reads this.
    direct_evidence_register_only: bool | None = None
    # #705: honest coupling summary attached on the FPR node-set fallback.
    coupled_residual: dict | None = None


def _target(inp: DeriveInputs, routing: Routing, *,
            target_roles: list | None = None,
            order_target: dict | None = None,
            class_evidence: str = "") -> OrderTarget:
    return OrderTarget(
        function=inp.function,
        unit=inp.unit,
        class_id=inp.class_id,
        phys_target=dict(inp.phys_target),
        phys_conflicts=list(inp.phys_conflicts),
        force_iter_first=list(inp.force_iter_first),
        order_target=dict(order_target or {}),
        target_roles=list(target_roles or []),
        unscored_roles=list(inp.unscored_roles),
        forced_decisions_sha256=list(inp.forced_decisions_sha256),
        baseline_source_sha256=inp.baseline_source_sha256,
        baseline_pcdump_sha256=inp.baseline_pcdump_sha256,
        routing=routing.value,
        class_evidence=class_evidence,
    )


def derive_order_target(inp: DeriveInputs) -> OrderTarget:
    # Step 1 — register-only precondition. A structural diff is not in this pool.
    if inp.checkdiff_primary not in REGISTER_ONLY_PRIMARIES:
        raise ValueError(
            f"{inp.function}: checkdiff primary is {inp.checkdiff_primary!r}, "
            f"not register-only ({sorted(REGISTER_ONLY_PRIMARIES)}); "
            f"not in the order-distance pool"
        )

    # Step 2 — phys conflict classifier (BEFORE any forced compile).
    # A phys conflict (same virtual -> >=2 target physregs at different sites)
    # is a NODE-SET-divergence signal: the candidate causes are upstream of
    # select (instruction-content/emission skew, coalescing, VN, or liveness),
    # not the order. The attribution is a lead to confirm, not a proof.
    if inp.phys_conflicts:
        igs = sorted({c.get("ig_idx") for c in inp.phys_conflicts if "ig_idx" in c})
        evidence = (
            "phys conflict ig" + ",ig".join(str(i) for i in igs)
            + ": same virtual wants multiple target physregs at different sites "
            "(node-set divergence upstream of select; confirm attribution)"
        ) if igs else (
            "phys conflict: same virtual wants multiple target physregs "
            "(node-set divergence upstream of select; confirm attribution)"
        )
        return _target(inp, Routing.NOT_ORDER_CLASS, class_evidence=evidence)

    # Step 3 — the 64-entry force cap. Routes ONLY on the collector's
    # minimal-set search verdict (B1), plus a contract guard on the chosen
    # list (a >64 list silently applies NOTHING in the DLL).
    if inp.force_cap_exceeded:
        return _target(
            inp, Routing.FORCE_CAP_BLOCKED,
            class_evidence=(
                f"no <= {FORCE_CAP}-entry forcing set eliminates the class "
                f"residual: the per-register anchor list exceeds the cap and "
                f"the {FORCE_CAP}-entry window probe did not byte-eliminate "
                f"(DLL cap raise is the named fix — a tooling task)"
            ),
        )
    if len(inp.force_iter_first) > FORCE_CAP:
        return _target(
            inp, Routing.FORCE_CAP_BLOCKED,
            class_evidence=(
                f"chosen forcing list has {len(inp.force_iter_first)} entries "
                f"(> {FORCE_CAP}); the DLL silently applies nothing beyond the "
                f"cap, so this set is unusable (collector contract violation)"
            ),
        )

    # Step 4a — verify application, POSITION-EXACT (B2). The ig at 0-based
    # list index i must sit at DECISIONS position i. Present-but-elsewhere is
    # a silent misapply; a force that did not apply must never produce a target.
    misapplied: list[str] = []
    for index, ig in enumerate(inp.force_iter_first):
        actual = inp.applied_positions.get(ig)
        if actual is None:
            misapplied.append(f"ig{ig}: absent from forced readback")
        elif actual != index:
            misapplied.append(
                f"ig{ig}: forced to position {index} but landed at {actual}"
            )
    if misapplied:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            class_evidence=(
                "forced igs did not apply at their forced positions ("
                + "; ".join(misapplied)
                + ") — silent no-op / stale DLL / cap overflow"
            ),
        )

    # Step 4b — class-partition gate.
    if not inp.forced_class_clean:
        return _target(
            inp, Routing.NOT_ORDER_CLASS,
            class_evidence=(
                "forced-ORDER build did not byte-eliminate the class residual; "
                "order is a symptom of instruction-content/emission divergence "
                "upstream of select (e.g. coalescing/VN/liveness/statement-copy skew)"
            ),
        )

    # Step 5 — ig-set identity between baseline and forced build.
    if inp.baseline_ig_set != inp.forced_ig_set:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            class_evidence=(
                "forced-build ig-set != baseline ig-set: forcing perturbed IG "
                "construction (target suspect)"
            ),
        )

    # Step 6 — target-role pruning (§3.3). Keep only baseline-self-reanchor-
    # confident roles that also have a rank in the forced build.
    target_roles = sorted(
        ig for ig in inp.self_reanchored_roles if ig in inp.forced_ranks
    )
    if len(target_roles) < 2:
        return _target(
            inp, Routing.UNANCHORABLE,
            class_evidence=(
                f"only {len(target_roles)} role(s) self-reanchor confidently; "
                f"Kendall needs >= 2 pairs"
            ),
        )
    order_target = {ig: inp.forced_ranks[ig] for ig in target_roles}

    # Step 7 — derive-twice determinism.
    hashes = inp.forced_decisions_sha256
    if len(hashes) < 2 or len(set(hashes)) != 1:
        return _target(
            inp, Routing.UNSTABLE_TARGET,
            order_target=order_target, target_roles=target_roles,
            class_evidence=(
                "derive-twice DECISIONS hashes differ: nondeterministic forced "
                "build (DLL/hook fault to investigate, never averaged)"
            ),
        )

    # All gates passed -> directed.
    return _target(
        inp, Routing.DIRECTED,
        order_target=order_target, target_roles=target_roles,
    )
