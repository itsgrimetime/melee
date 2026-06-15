from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.probe import (
    caller_visible_source_of, derive_probe_context, first_def_opcode_of,
    is_window_order_residual, source_attr_of, source_object_of,
)
from src.search.solver.types import Perturbation, PerturbationKind


class _FakeFirstDef:
    def __init__(self, opcode):
        self.opcode = opcode


class _FakeSource:
    """Minimal raw SourceAttribution stand-in: probe.py reads kind/name/
    source_file/source_line/first_def.opcode (Amendment A2)."""
    def __init__(self, *, kind="local", name=None, expression=None,
                 source_file=None, source_line=None, first_def_opcode=None):
        self.kind = kind
        self.name = name
        self.expression = expression
        self.source_file = source_file
        self.source_line = source_line
        self.first_def = (_FakeFirstDef(first_def_opcode)
                          if first_def_opcode is not None else None)


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
                               source=_FakeSource(name="x"),
                               window_residual=False)
    assert ctx.is_runtime_value is False


def test_lis_defined_is_not_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lis",
                               source=_FakeSource(name="x"),
                               window_residual=False)
    assert ctx.is_runtime_value is False


def test_unknown_first_def_is_admitted_as_runtime():
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode=None,
                               source=_FakeSource(name="x"),
                               window_residual=False)
    assert ctx.is_runtime_value is True


# --- L2(b) Amendment A2: caller visibility from provenance KIND, not name/line ---
def test_synthetic_implicit_temp_is_not_caller_visible():
    # implicit-temp (addi/rlwinm product) has NO source-level variable -> reject_b.
    src = _FakeSource(kind="implicit-temp", expression="addi r55,r54,1",
                      first_def_opcode="addi")
    assert caller_visible_source_of(src) is False
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="addi",
                               source=src, window_residual=False)
    assert ctx.caller_visible_source is False


def test_synthetic_copy_coalesce_product_is_not_caller_visible():
    src = _FakeSource(kind="copy/coalesce-product", expression="mr r70,r69",
                      first_def_opcode="mr")
    assert caller_visible_source_of(src) is False


def test_nameless_lineless_first_def_is_not_caller_visible():
    # a first-def with NO name AND no source_line -> no caller boundary -> reject_b.
    src = _FakeSource(kind="first-def", name=None, source_line=None,
                      expression="lis r60,17200", first_def_opcode="lis")
    assert caller_visible_source_of(src) is False


def test_absent_source_is_not_caller_visible():
    # source=None (attribution blind spot) -> no source variable -> reject_b.
    assert caller_visible_source_of(None) is False
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode=None,
                               source=None, window_residual=False)
    assert ctx.caller_visible_source is False


def test_named_local_is_caller_visible():
    # the win-lever class: a named source-level local/param is ALWAYS admitted.
    src = _FakeSource(kind="local", name="data", expression="data",
                      source_file="src/melee/mn/mndiagram.c", source_line=2050)
    assert caller_visible_source_of(src) is True
    ctx = derive_probe_context(_node_add(), _ig(), first_def_opcode="lwz",
                               source=src, window_residual=False)
    assert ctx.caller_visible_source is True


def test_named_param_is_caller_visible():
    src = _FakeSource(kind="param", name="nana_gobj", expression="nana_gobj",
                      source_file="f.c", source_line=951)
    assert caller_visible_source_of(src) is True


def test_named_call_return_is_caller_visible():
    # a call-return bound to a named local (temp_r31) is a caller-level value.
    src = _FakeSource(kind="call-return", name="temp_r31",
                      expression="gmMainLib_8015EDA4()")
    assert caller_visible_source_of(src) is True


def test_field_load_alias_is_caller_visible_despite_name_none():
    # A2 caution: a field-access alias (name=None) is a REALIZABLE alias-intro
    # lever (T x = gobj->f; ...), NOT a reject. Must NOT use name-presence.
    src = _FakeSource(kind="field-load", name=None,
                      expression="nana_gobj->field_at_0x2C",
                      source_file="src/melee/ft/chara/ftNana/ftNn_Init.c",
                      source_line=951)
    assert caller_visible_source_of(src) is True


# --- source_attr_of: raw attribution accessor (A2) ---
def test_source_attr_of_returns_raw_source_and_none():
    class _Src:
        kind = "local"
        name = "v"
    class _VA:
        def __init__(self, ig_idx, source):
            self.ig_idx = ig_idx
            self.source = source
    class _Report:
        virtuals = (_VA(41, _Src()), _VA(50, None))
    assert source_attr_of(_Report(), 41).kind == "local"
    assert source_attr_of(_Report(), 50) is None
    assert source_attr_of(_Report(), 999) is None


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
                               source=_FakeSource(kind="local", name="x"),
                               window_residual=True)
    assert ctx.copy_already_survives is True


# --- L1: strict-subset survival rule ---
def test_routing_all_uses_is_coalesce_bait():
    p = _node_add(target=41, use_set=(40, 42, 43))   # ALL of 41's neighbors
    ctx = derive_probe_context(p, _ig(), first_def_opcode="lwz",
                               source=_FakeSource(kind="local", name="x"),
                               window_residual=False)
    assert ctx.original_keeps_use_past_vprime is False


def test_routing_proper_subset_keeps_a_use():
    p = _node_add(target=41, use_set=(42,))
    ctx = derive_probe_context(p, _ig(), first_def_opcode="lwz",
                               source=_FakeSource(kind="local", name="x"),
                               window_residual=False)
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
                               source=None, window_residual=False)
    for field in ("is_runtime_value", "caller_visible_source",
                  "copy_already_survives", "original_keeps_use_past_vprime"):
        assert type(getattr(ctx, field)) is bool, field
    # caller_visible_source_of also must return a strict bool on a degenerate src.
    assert type(caller_visible_source_of(None)) is bool
