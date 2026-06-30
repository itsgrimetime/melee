import pytest

from src.mwcc_debug.tiebreak import IG, IGNode, predict_assignments
from src.search.solver.perturbations import apply, add_node, add_edge, remove_edge, move_order
from src.search.solver.types import Perturbation, PerturbationKind


def _ig():
    nodes = {
        40: IGNode(40, {41}, {}, 1, False, 31),
        41: IGNode(41, {40, 42}, {}, 2, False, 30),
        42: IGNode(42, {41}, {}, 1, False, 29),
    }
    return IG(class_id=0, select_order=[40, 41, 42], nodes=nodes,
              decision_igs={40, 41, 42})


def test_add_node_routes_uses_and_overlap_edge():
    ig2 = add_node(_ig(), source_ig=41, new_ig=99, route_neighbors={42},
                   position="after", interfere_original=True)
    assert 99 in ig2.nodes
    assert 42 in ig2.nodes[99].neighbors and 41 in ig2.nodes[99].neighbors
    assert 42 not in ig2.nodes[41].neighbors and 99 in ig2.nodes[41].neighbors
    assert 99 in ig2.nodes[42].neighbors           # symmetric on the routed side
    assert ig2.select_order.index(99) == ig2.select_order.index(41) + 1
    assert 99 not in _ig().nodes                    # pure


def test_add_node_no_interference_omits_vprime_edge():
    ig2 = add_node(_ig(), source_ig=41, new_ig=99, route_neighbors={42},
                   position="before", interfere_original=False)
    assert 41 not in ig2.nodes[99].neighbors
    assert ig2.select_order.index(99) == ig2.select_order.index(41) - 1


def test_add_node_surrogate_predicts_over_perturbed_ig():
    ig2 = add_node(_ig(), source_ig=41, new_ig=99, route_neighbors={42},
                   position="after", interfere_original=True)
    assigns = predict_assignments(ig2)
    assert 99 in assigns and 41 in assigns


def test_add_edge_and_remove_edge_roundtrip():
    base = _ig()
    with_edge = add_edge(base, 40, 42)
    assert 42 in with_edge.nodes[40].neighbors and 40 in with_edge.nodes[42].neighbors
    without = remove_edge(with_edge, 40, 42)
    assert 42 not in without.nodes[40].neighbors


def test_remove_edge_reproduces_v1_remove_88_37():
    # v1 case: remove(88,37) -> ig88 changes register. 37 is a precolored
    # neighbor pinning reg 0 (the lowest legal physical), so with the edge
    # present 88 is forced off 0; removing the edge lets it drop back to 0.
    nodes = {
        88: IGNode(88, {37}, {37: 0}, 1, False, 0),
        37: IGNode(37, {88}, {}, 1, False, 0),
    }
    ig = IG(class_id=0, select_order=[37, 88], nodes=nodes, decision_igs={37, 88})
    base = predict_assignments(ig)
    after = predict_assignments(remove_edge(ig, 88, 37))
    assert after[88] != base[88]


def test_move_order_changes_select_position():
    ig2 = move_order(_ig(), target_ig=42, position="before", anchor_ig=40)
    assert ig2.select_order.index(42) < ig2.select_order.index(40)


def test_apply_dispatches_each_kind():
    base = _ig()
    p_node = Perturbation(PerturbationKind.NODE_ADD, target_ig=41, use_set=(42,),
                          new_ig=99, position="after", interfere_original=True)
    assert 99 in apply(base, p_node).nodes
    p_edge = Perturbation(PerturbationKind.EDGE_ADD, target_ig=40, edge=(40, 42))
    assert 42 in apply(base, p_edge).nodes[40].neighbors
    p_rm = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=41, edge=(41, 42))
    assert 42 not in apply(base, p_rm).nodes[41].neighbors
    p_ord = Perturbation(PerturbationKind.ORDER, target_ig=42,
                         order_move=("before", 40))
    assert apply(base, p_ord).select_order.index(42) < 1


def test_apply_coalesce_requires_flag():
    base = _ig()
    p = Perturbation(PerturbationKind.COALESCE, target_ig=41)
    with pytest.raises(ValueError, match="experimental"):
        apply(base, p)
    out = apply(base, p, allow_experimental=True)
    assert isinstance(out, IG)
