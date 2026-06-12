import pytest

from src.mwcc_debug.order_target_derive import derive_order_target, DeriveInputs
from src.search.directed.order_target import Routing


def _inputs(**over):
    """Build a DeriveInputs whose default tool outputs describe a clean,
    directed, two-role function (mnDiagram_OnFrame-shaped).

    Internally consistent with --force-iter-first semantics: the forced list
    [46, 28, 29] occupies DECISIONS positions 0,1,2 (ranks 1,2,3); unforced
    ig31 follows at rank 4.
    """
    base = dict(
        function="mnDiagram_OnFrame",
        unit="melee/mn/mndiagram",
        class_id=0,
        # Step 1: register-only checkdiff primary.
        checkdiff_primary="operand-register-or-offset",
        # Step 2: force-phys-from-diff.
        phys_target={28: 29, 29: 28},
        phys_conflicts=[],
        # Step 3: the CHOSEN (minimal, <=64) forcing list + the search verdict.
        force_iter_first=[46, 28, 29],
        # Step 4 verify-application: {forced_ig: 0-based DECISIONS position}.
        applied_positions={46: 0, 28: 1, 29: 2},
        # Step 4: the union probe byte-eliminated the class residual.
        forced_class_clean=True,
        # Step 5: the forced build's COLORGRAPH ranks {ig: rank} (1-based).
        forced_ranks={46: 1, 28: 2, 29: 3, 31: 4},
        baseline_ig_set={46, 28, 29, 31},
        forced_ig_set={46, 28, 29, 31},
        # Step 6: roles that self-reanchor MATCHED on the baseline.
        self_reanchored_roles={28, 29},
        unscored_roles=[{"ig": 31, "reason": "ambiguous_signature"}],
        # Step 7: two forced DECISIONS-section hashes.
        forced_decisions_sha256=["hashA", "hashA"],
        baseline_source_sha256="src1",
        baseline_pcdump_sha256="pc1",
        # B1: True ONLY when anchors > 64 AND no <=64 window eliminated.
        force_cap_exceeded=False,
    )
    base.update(over)
    return DeriveInputs(**base)


def test_clean_two_role_routes_directed():
    t = derive_order_target(_inputs())
    assert t.routing == Routing.DIRECTED.value
    assert t.target_roles == [28, 29]
    assert t.order_target == {28: 2, 29: 3}
    assert t.exit_code() == 0


def test_structural_diff_aborts_before_pool():
    with pytest.raises(ValueError, match="register-only"):
        derive_order_target(_inputs(checkdiff_primary="control-flow-source-shape"))


def test_backend_ceiling_primary_is_admitted():
    # backend-ceiling (coloring-rotation) has matching opcode sequences; the
    # step-4 class gate is the outcome-verified arbiter.
    t = derive_order_target(_inputs(checkdiff_primary="backend-ceiling"))
    assert t.routing == Routing.DIRECTED.value


def test_normalized_structural_match_admitted():
    # normalized-structural-match = the #576 "zero structural diff demotion"
    # (FULLNORM-0): the masked diff is structurally ZERO, i.e. a pure register
    # residual — the pool's strongest admission signal. Must proceed past the
    # Step-1 precondition (T6 ruling; round-1 mis-rejected fn_803ACD58).
    t = derive_order_target(
        _inputs(checkdiff_primary="normalized-structural-match")
    )
    assert t.routing == Routing.DIRECTED.value


def test_phys_conflict_routes_not_order_class_early():
    t = derive_order_target(_inputs(
        phys_conflicts=[{"ig_idx": 56, "existing_phys": 29, "conflicting_phys": 28}]))
    assert t.routing == Routing.NOT_ORDER_CLASS.value
    assert "ig56" in t.class_evidence or "56" in t.class_evidence
    assert t.exit_code() == 4


def test_force_cap_blocked_only_when_no_minimal_set_found():
    # B1: the classifier routes on the SEARCH verdict, never raw list length —
    # the collector already tried the <=64 window before setting this flag.
    t = derive_order_target(_inputs(force_cap_exceeded=True))
    assert t.routing == Routing.FORCE_CAP_BLOCKED.value
    assert t.exit_code() == 5


def test_oversized_chosen_set_is_force_cap_blocked():
    # Contract guard: a >64 chosen set can never be applied (silent DLL no-op).
    t = derive_order_target(_inputs(force_iter_first=list(range(65))))
    assert t.routing == Routing.FORCE_CAP_BLOCKED.value


def test_force_not_applied_routes_unstable_target():
    # ig29 was forced but absent from the readback (silent no-op).
    t = derive_order_target(_inputs(applied_positions={46: 0, 28: 1}))
    assert t.routing == Routing.UNSTABLE_TARGET.value
    assert t.exit_code() == 6


def test_force_applied_at_wrong_position_routes_unstable_target():
    # B2: present-but-elsewhere is a silent misapply, not an application.
    # ig28 was forced to position 1 but landed at position 3.
    t = derive_order_target(_inputs(applied_positions={46: 0, 28: 3, 29: 2}))
    assert t.routing == Routing.UNSTABLE_TARGET.value
    assert "position" in t.class_evidence


def test_class_residual_not_eliminated_routes_not_order_class():
    t = derive_order_target(_inputs(forced_class_clean=False))
    assert t.routing == Routing.NOT_ORDER_CLASS.value
    assert t.exit_code() == 4


def test_ig_set_drift_routes_unstable_target():
    t = derive_order_target(_inputs(forced_ig_set={46, 28, 29}))  # 31 vanished
    assert t.routing == Routing.UNSTABLE_TARGET.value


def test_fewer_than_two_roles_routes_unanchorable():
    t = derive_order_target(_inputs(self_reanchored_roles={28}))
    assert t.routing == Routing.UNANCHORABLE.value
    assert t.exit_code() == 3


def test_determinism_mismatch_routes_unstable_target():
    t = derive_order_target(_inputs(forced_decisions_sha256=["hashA", "hashB"]))
    assert t.routing == Routing.UNSTABLE_TARGET.value


def test_directed_target_validates():
    from src.search.directed.order_target import validate_order_target
    validate_order_target(derive_order_target(_inputs()))  # no raise
