from src.search.directed.gate import evaluate_phase1_gate, GateVerdict


def _meta(valid=True, case="B", applied_mutator="reorder_local_decls",
          displacement=0.6, displacement_delta=0.2, reanchor_matched=2, reanchor_total=2,
          non_actionable=False):
    from src.search.directed.contracts import DirectedMeta
    return DirectedMeta(candidate_id="c", source_hash="s", iteration=0, parent_id=None,
        parent_state_id="root", valid=valid, invalid_reason=None, case=case, label="SAME",
        order_distance=1, displacement=displacement, displacement_delta=displacement_delta,
        reanchor_matched=reanchor_matched, reanchor_total=reanchor_total, diagnosis_chars=1,
        applied_mutator=applied_mutator, directed_scalar=displacement,
        non_actionable=non_actionable)


def test_pass_on_attributable_displacement():
    v = evaluate_phase1_gate(preflight_ok=True, telemetry=[_meta()], control_displacement=0.0)
    assert v.passed is True


def test_fail_not_preflight():
    assert evaluate_phase1_gate(False, [_meta()], 0.0).passed is False
    assert evaluate_phase1_gate(False, [_meta()], 0.0).reason == "not_preflight"


def test_fail_void_no_treatment():
    v = evaluate_phase1_gate(True, [], 0.0)
    assert v.passed is False and v.reason == "void_no_treatment"
    v2 = evaluate_phase1_gate(True, [_meta(valid=False)], 0.0)   # only invalid metas
    assert v2.passed is False and v2.reason == "void_no_treatment"
    v3 = evaluate_phase1_gate(True, [_meta(case="abstained")], 0.0)  # abstained excluded from treatment
    assert v3.passed is False and v3.reason == "void_no_treatment"


def test_fail_unattributed():
    v = evaluate_phase1_gate(True, [_meta(applied_mutator=None)], 0.0)
    assert v.passed is False and v.reason == "unattributed_or_regressing"


def test_no_smooth_gradient_is_distinct():
    v = evaluate_phase1_gate(True, [_meta(displacement_delta=0.0)], 0.0)
    assert v.passed is False and v.reason == "no_smooth_gradient"


def test_fail_low_coverage():
    v = evaluate_phase1_gate(True, [_meta(reanchor_matched=0, reanchor_total=2)], 0.0)
    assert v.passed is False     # coverage 0/2 < floor -> not a passing candidate


def test_fail_displacement_not_above_control():
    v = evaluate_phase1_gate(True, [_meta(displacement=0.2, displacement_delta=0.1)], control_displacement=0.5)
    assert v.passed is False     # displacement 0.2 <= control 0.5


def test_non_actionable_candidate_cannot_pass():
    # Attribution integrity (Codex round 4 P0): a candidate from the blind
    # var_name=None fallback is marked non_actionable; even with a perfect
    # phys-match it must NOT satisfy the gate's attribution requirement.
    v = evaluate_phase1_gate(
        True,
        [_meta(displacement=1.0, displacement_delta=1.0, non_actionable=True)],
        control_displacement=0.0,
    )
    assert v.passed is False
    # It IS covered + valid treatment, so it routes to no_smooth_gradient (a
    # real, attributed-but-no-win signal is absent) rather than a hollow pass.
    assert v.reason in {"no_smooth_gradient", "unattributed_or_regressing"}


def test_phys_match_above_real_control_passes():
    # An ACTIONABLE candidate that beats the real control's phys-match passes.
    v = evaluate_phase1_gate(
        True,
        [_meta(displacement=0.5, displacement_delta=0.5)],
        control_displacement=0.0,   # the real 9ACC-style wall baseline (0/N)
    )
    assert v.passed is True and v.reason == "attributable_progress"


def test_no_smooth_gradient_when_attributed_but_no_win():
    # Mechanism is diagnosing + attributing (actionable) but no candidate beat
    # control's phys-match: the honest Phase-1 "no gradient" outcome.
    v = evaluate_phase1_gate(
        True,
        [_meta(displacement=0.0, displacement_delta=0.0)],
        control_displacement=0.0,
    )
    assert v.passed is False and v.reason == "no_smooth_gradient"
    assert "control_displacement" in v.evidence
