from src.search.solver.types import Perturbation, PerturbationKind, serialize_perturbation


def test_perturbation_kinds():
    assert {k.value for k in PerturbationKind} == {
        "node-add", "edge-add", "edge-remove", "order", "coalesce",
    }


def test_node_add_perturbation_shape():
    p = Perturbation(
        kind=PerturbationKind.NODE_ADD, target_ig=41,
        use_set=(42,), new_ig=99, position="after", interfere_original=True,
    )
    assert p.kind is PerturbationKind.NODE_ADD
    assert p.target_ig == 41 and p.use_set == (42,)
    assert p.edge is None and p.order_move is None


def test_edge_perturbation_shape():
    p = Perturbation(kind=PerturbationKind.EDGE_ADD, target_ig=88, edge=(88, 37))
    assert p.edge == (88, 37) and p.use_set is None


def test_order_perturbation_shape():
    p = Perturbation(kind=PerturbationKind.ORDER, target_ig=40,
                     order_move=("before", 33))
    assert p.order_move == ("before", 33)


def test_serialize_matches_schema_fields_only():
    # Spec §7 candidate.perturbation = {kind, target_ig, use_set?, edge?, order_move?}.
    p = Perturbation(PerturbationKind.NODE_ADD, target_ig=41, use_set=(42,),
                     new_ig=99, position="after", interfere_original=True)
    assert serialize_perturbation(p) == {"kind": "node-add", "target_ig": 41,
                                         "use_set": [42]}
    p2 = Perturbation(PerturbationKind.EDGE_REMOVE, target_ig=88, edge=(88, 37))
    assert serialize_perturbation(p2) == {"kind": "edge-remove", "target_ig": 88,
                                          "edge": [88, 37]}
    p3 = Perturbation(PerturbationKind.ORDER, target_ig=40, order_move=("before", 33))
    assert serialize_perturbation(p3) == {"kind": "order", "target_ig": 40,
                                          "order_move": ["before", 33]}
