"""§1 perturbation vocabulary as pure IG-edit functions over tiebreak.IG.

Every function returns a NEW IG (the surrogate is never mutated). apply() is the
dispatcher; node-add is the project's center of gravity, edge and order are the
v1 default companions, coalesce is gated behind a flag (§1d).
"""
from __future__ import annotations

import copy

from src.mwcc_debug.tiebreak import IG, IGNode
from src.search.solver.types import Perturbation, PerturbationKind


def add_node(ig, *, source_ig, new_ig, route_neighbors, position,
             interfere_original):
    """§1a node-add: insert V' (new_ig) copying source_ig, routing a subset of
    its neighbors onto V' and (optionally) adding the V'-V overlap edge."""
    if new_ig in ig.nodes:
        raise ValueError(f"new_ig {new_ig} already present")
    src = ig.nodes[source_ig]
    routed = set(route_neighbors) & set(src.neighbors)
    nodes = copy.deepcopy(ig.nodes)

    vprime_nbrs = set(routed) | ({source_ig} if interfere_original else set())
    vprime_pre = {n: src.precolored[n] for n in routed if n in src.precolored}
    nodes[new_ig] = IGNode(new_ig, vprime_nbrs, vprime_pre, len(vprime_nbrs),
                           False, -1)

    v = nodes[source_ig]
    v.neighbors = (set(v.neighbors) - routed) | ({new_ig} if interfere_original else set())
    v.array_size = len(v.neighbors)
    for n in routed:
        if n in nodes:
            nb = nodes[n]
            nb.neighbors = (set(nb.neighbors) - {source_ig}) | {new_ig}

    order = list(ig.select_order)
    idx = order.index(source_ig)
    order.insert(idx + (1 if position == "after" else 0), new_ig)
    return IG(ig.class_id, order, nodes, set(ig.decision_igs) | {new_ig})


def _with_edge(ig, a, b, *, present):
    nodes = copy.deepcopy(ig.nodes)
    for x, y in ((a, b), (b, a)):
        if x in nodes:
            nbrs = set(nodes[x].neighbors)
            if present:
                nbrs.add(y)
            else:
                nbrs.discard(y)
            nodes[x].neighbors = nbrs
            nodes[x].array_size = len(nbrs)
    return IG(ig.class_id, list(ig.select_order), nodes, set(ig.decision_igs))


def add_edge(ig, a, b):
    return _with_edge(ig, a, b, present=True)


def remove_edge(ig, a, b):
    return _with_edge(ig, a, b, present=False)


def move_order(ig, *, target_ig, position, anchor_ig):
    order = list(ig.select_order)
    if target_ig not in order or anchor_ig not in order:
        return IG(ig.class_id, order, copy.deepcopy(ig.nodes), set(ig.decision_igs))
    order.remove(target_ig)
    i = order.index(anchor_ig)
    order.insert(i + (1 if position == "after" else 0), target_ig)
    return IG(ig.class_id, order, copy.deepcopy(ig.nodes), set(ig.decision_igs))


def _coalesce(ig, target_ig):
    # Experimental (§1d): v1 default never reaches here.
    return IG(ig.class_id, list(ig.select_order), copy.deepcopy(ig.nodes),
              set(ig.decision_igs))


def apply(ig: IG, p: Perturbation, *, allow_experimental: bool = False) -> IG:
    if p.kind is PerturbationKind.NODE_ADD:
        return add_node(ig, source_ig=p.target_ig, new_ig=p.new_ig,
                        route_neighbors=set(p.use_set or ()),
                        position=p.position,
                        interfere_original=bool(p.interfere_original))
    if p.kind is PerturbationKind.EDGE_ADD:
        return add_edge(ig, *p.edge)
    if p.kind is PerturbationKind.EDGE_REMOVE:
        return remove_edge(ig, *p.edge)
    if p.kind is PerturbationKind.ORDER:
        pos, anchor = p.order_move
        return move_order(ig, target_ig=p.target_ig, position=pos, anchor_ig=anchor)
    if p.kind is PerturbationKind.COALESCE:
        if not allow_experimental:
            raise ValueError("coalesce is experimental (spec §1d); pass "
                             "allow_experimental=True / --experimental-kinds coalesce")
        return _coalesce(ig, p.target_ig)
    raise ValueError(f"unknown perturbation kind {p.kind!r}")
