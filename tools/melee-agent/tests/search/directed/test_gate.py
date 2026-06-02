from src.search.directed.gate import evaluate_phase1_gate, GateVerdict


def _meta(valid=True, case="B", applied_mutator="reorder_local_decls",
          displacement=0.6, displacement_delta=0.2, reanchor_matched=2, reanchor_total=2):
    from src.search.directed.contracts import DirectedMeta
    return DirectedMeta(candidate_id="c", source_hash="s", iteration=0, parent_id=None,
        parent_state_id="root", valid=valid, invalid_reason=None, case=case, label="SAME",
        order_distance=1, displacement=displacement, displacement_delta=displacement_delta,
        reanchor_matched=reanchor_matched, reanchor_total=reanchor_total, diagnosis_chars=1,
        applied_mutator=applied_mutator, directed_scalar=displacement)


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
