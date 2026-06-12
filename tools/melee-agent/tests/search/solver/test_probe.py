from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.probe import (
    derive_probe_context, first_def_opcode_of, is_window_order_residual,
    source_object_of,
)
from src.search.solver.types import Perturbation, PerturbationKind


def _ig(observed_42=22):
    nodes = {
        40: IGNode(40, {41}, {}, 1, False, 31),
        41: IGNode(41, {40, 42, 43}, {}, 3, False, 30),
        42: IGNode(42, {41}, {}, 1, False, observed_42),
        43: IGNode(43, {41}, {}, 1, False, 20),
    }
    return IG(class_id=0, select_order=[40, 41, 42, 43], nodes=nodes,
              decision_igs={40, 41, 42, 43})


def _node_add(target=41, use_set=(42,)):
    return Perturbation(PerturbationKind.NODE_ADD, target_ig=target,
                        use_set=use_set, new_ig=99, position="after",
                        interfere_original=True)


# --- L2(a): runtime vs li/lis constant ---
def test_constant_li_defined_is_not_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="li",
                               source_object="x", window_residual=False)
    assert ctx.is_runtime_value is False


def test_lis_defined_is_not_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lis",
                               source_object="x", window_residual=False)
    assert ctx.is_runtime_value is False


def test_unknown_first_def_is_admitted_as_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode=None,
                               source_object="x", window_residual=False)
    assert ctx.is_runtime_value is True


# --- L2(b): caller visibility from the resolved source object ---
def test_no_source_object_is_not_caller_visible():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lwz",
                               source_object=None, window_residual=False)
    assert ctx.caller_visible_source is False


# --- L2(c): window-shift residual classifier ---
def test_uniform_callee_save_shift_is_window_residual():
    # observed r22/r20 vs desired r21/r19: uniform +1 shift on callee-saves.
    assert is_window_order_residual(_ig(observed_42=22), {42: 21, 43: 19}) is True


def test_mixed_deltas_are_not_window_residual():
    # 42: 22->21 (+1) but 43: 20->17 (+3): not a uniform shift.
    assert is_window_order_residual(_ig(observed_42=22), {42: 21, 43: 17}) is False


def test_volatile_target_is_not_window_residual():
    # desired r3 is a volatile, not a callee-save window member.
    assert is_window_order_residual(_ig(observed_42=4), {42: 3}) is False


def test_window_residual_flags_copy_already_survives():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lwz",
                               source_object="x", window_residual=True)
    assert ctx.copy_already_survives is True


# --- L1: strict-subset survival rule ---
def test_routing_all_uses_is_coalesce_bait():
    p = _node_add(target=41, use_set=(40, 42, 43))   # ALL of 41's neighbors
    ctx = derive_probe_context(p, _ig(), first_def_opcode="lwz",
                               source_object="x", window_residual=False)
    assert ctx.original_keeps_use_past_vprime is False


def test_routing_proper_subset_keeps_a_use():
    p = _node_add(target=41, use_set=(42,))
    ctx = derive_probe_context(p, _ig(), first_def_opcode="lwz",
                               source_object="x", window_residual=False)
    assert ctx.original_keeps_use_past_vprime is True


# --- report accessors: explain_virtuals report -> name / first-def opcode ---
def test_report_accessors_handle_none_and_named():
    class _FD:
        opcode = "li"
    class _Src:
        name = "row_text"
        expression = None
        first_def = _FD()
    class _VA:
        def __init__(self, ig_idx, source):
            self.ig_idx = ig_idx
            self.source = source
    class _Report:
        virtuals = (_VA(41, _Src()), _VA(50, None))

    assert source_object_of(_Report(), 41) == "row_text"
    assert source_object_of(_Report(), 50) is None
    assert source_object_of(_Report(), 999) is None
    assert first_def_opcode_of(_Report(), 41) == "li"
    assert first_def_opcode_of(_Report(), 50) is None


# --- T3-REVIEW-MANDATED: derivations return REAL booleans on degenerate/absent
# inputs (validity.passes_1_5_filter does NO value-validation; a ProbeContext
# carrying a None field would be SILENTLY ADMITTED, so probe.py must guarantee
# strict bools on every path). Asserts type identity (not mere truthiness) so a
# leaked None/Optional would FAIL here even though `not None`/`X is not None`
# would mask it downstream.
def test_derivations_return_strict_bool_on_absent_inputs():
    # Degenerate: empty report (no virtuals), missing keys, all-absent signals.
    class _EmptyReport:
        virtuals = ()

    # Report accessors on an empty/missing report stay Optional[str] (None is
    # the documented conservative absent value, NOT a bool) -- but the four
    # ProbeContext signals fed to the filter must be real bools regardless.
    assert source_object_of(_EmptyReport(), 41) is None
    assert first_def_opcode_of(_EmptyReport(), 41) is None

    # is_window_order_residual: degenerate phys_target (empty) and a target
    # naming a missing node must both yield a strict bool, never None/truthy.
    empty_target = is_window_order_residual(_ig(), {})
    missing_node = is_window_order_residual(_ig(), {999: 21})
    assert type(empty_target) is bool and empty_target is False
    assert type(missing_node) is bool and missing_node is False

    # derive_probe_context with ALL signals absent (None first-def, None source,
    # window_residual False) and a target whose node is absent from the IG:
    # every field of the returned ProbeContext must be a strict bool.
    p = Perturbation(PerturbationKind.NODE_ADD, target_ig=12345,
                     use_set=None, new_ig=99, position="after",
                     interfere_original=True)
    ctx = derive_probe_context(p, _ig(), first_def_opcode=None,
                               source_object=None, window_residual=False)
    for field in ("is_runtime_value", "caller_visible_source",
                  "copy_already_survives", "original_keeps_use_past_vprime"):
        assert type(getattr(ctx, field)) is bool, field
