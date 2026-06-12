from src.search.solver.types import Perturbation, PerturbationKind
from src.search.solver.validity import ProbeContext, FilterVerdict, passes_1_5_filter


def _node_add(source_ig=41, use_set=(42,)):
    return Perturbation(PerturbationKind.NODE_ADD, target_ig=source_ig,
                        use_set=use_set, new_ig=99, position="after",
                        interfere_original=True)


def _ctx(**over):
    base = dict(
        is_runtime_value=True,                 # L2(a)
        caller_visible_source=True,            # L2(b)
        copy_already_survives=False,           # L2(c)
        original_keeps_use_past_vprime=True,   # L1
    )
    base.update(over)
    return ProbeContext(**base)


def test_admit_ftco_shaped_runtime_caller_visible_interfering():
    v = passes_1_5_filter(_node_add(), _ctx())
    assert v.admit is True and v.reason is None and v.flag is None


def test_reject_a_constant():
    v = passes_1_5_filter(_node_add(), _ctx(is_runtime_value=False))
    assert v.admit is False and v.reason == "rejected_a"


def test_reject_b_intra_inline():
    v = passes_1_5_filter(_node_add(), _ctx(caller_visible_source=False))
    assert v.admit is False and v.reason == "rejected_b"


def test_reject_survival_coalesce_bait():
    v = passes_1_5_filter(_node_add(), _ctx(original_keeps_use_past_vprime=False))
    assert v.admit is False and v.reason == "rejected_survival"


def test_flag_c_window_order():
    # flag-and-quarantine, NOT a hard reject: still evaluated, routed to the
    # window_order bucket, never an apply recommendation (spec §1.5 (c)).
    v = passes_1_5_filter(_node_add(), _ctx(copy_already_survives=True))
    assert v.admit is False and v.flag == "flagged_c" and v.reason is None


def test_non_node_add_is_admitted_unconditionally():
    p = Perturbation(PerturbationKind.EDGE_ADD, target_ig=40, edge=(40, 42))
    v = passes_1_5_filter(p, _ctx(is_runtime_value=False))
    assert v.admit is True
