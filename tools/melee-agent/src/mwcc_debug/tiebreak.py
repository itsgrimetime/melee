"""Register-coloring tiebreak surrogate + what-if solver (spec
docs/superpowers/specs/2026-06-10-tiebreak-counterfactual-design.md).

The pcdump's COLORGRAPH DECISIONS section is the allocator's decision phase laid
bare: each node (ig_idx) with its full interferer set (each paired with the
interferer's assigned physical), in observed SELECT order, plus the observed
assignment. We reimplement only the SELECT phase ("given the order, what reg
does each node get?") — the G1 question — and validate it to 100% against real
dumps. Then we answer what-ifs: if node N had one more/less interferer, or moved
in the select order, what register would it get? That turns a coloring tiebreak
from blind permuter search into a checked, source-actionable objective.

We do NOT predict the select order from the IG (that is degree-priority/
constrained-first, an open problem here, ~1-35% — the spec drops it); the order
is always taken from the dump and perturbed locally.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .colorgraph_parser import (ColorgraphDecision, ColorgraphSection,
                                 FunctionEvents, find_function,
                                 parse_hook_events)

# PowerPC GPR pools. Volatiles tried lowest-first (r0 is the lowest volatile).
# Callee-saves: reuse an already-dispensed one (ascending) before allocating a
# fresh one from r31 downward.
_VOLATILE_LOW_FIRST = [0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
_CALLEE_FRESH = [31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20,
                 19, 18, 17, 16, 15, 14, 13]
_CALLEE_SET = set(_CALLEE_FRESH)
SPILL = -1


@dataclass
class IGNode:
    ig_idx: int
    neighbors: set[int]              # interferer ig_idx values
    precolored: dict[int, int]       # interferer_idx -> reg, for non-virtual nbrs
    array_size: int                  # original interferer count
    incomplete: bool                 # interferer list was truncated (...N more)
    observed_reg: int


@dataclass
class IG:
    class_id: int
    select_order: list[int]          # ig_idx in observed select order
    nodes: dict[int, IGNode]
    decision_igs: set[int]


def build_ig(section: ColorgraphSection) -> IG:
    """Materialize the interference graph + observed select order from a
    COLORGRAPH DECISIONS section."""
    decisions = sorted(section.decisions, key=lambda d: d.iter_idx)
    decision_igs = {d.ig_idx for d in decisions}
    nodes: dict[int, IGNode] = {}
    for d in decisions:
        neighbors = {iidx for iidx, _ in d.interferers}
        # A neighbor that isn't a colorable virtual node blocks a fixed register:
        #  - machine-reg interferer (iidx 0..31) blocks ITS OWN number r<iidx>
        #    (the paired reg field is sometimes -1 for these; ignore it);
        #  - a coalesce-ghost (iidx>=32, no own decision row) blocks its resolved
        #    physical (the paired reg, when >= 0).
        precolored: dict[int, int] = {}
        for iidx, reg in d.interferers:
            if iidx < 32:
                precolored[iidx] = iidx
            elif iidx not in decision_igs and reg >= 0:
                precolored[iidx] = reg
        incomplete = len(d.interferers) < d.n_interferers
        nodes[d.ig_idx] = IGNode(
            ig_idx=d.ig_idx, neighbors=neighbors, precolored=precolored,
            array_size=d.n_interferers, incomplete=incomplete,
            observed_reg=d.assigned_reg)
    return IG(class_id=section.class_id,
              select_order=[d.ig_idx for d in decisions],
              nodes=nodes, decision_igs=decision_igs)


def _pick(blocked: set[int], dispensed: set[int]) -> int:
    for r in _VOLATILE_LOW_FIRST:
        if r not in blocked:
            return r
    for r in sorted(dispensed):           # reuse dispensed callee-saves ascending
        if r not in blocked:
            return r
    for r in _CALLEE_FRESH:               # fresh callee-save, r31 downward
        if r not in dispensed and r not in blocked:
            return r
    return SPILL


def predict_assignments(ig: IG, *, order: list[int] | None = None,
                        extra_neighbors: dict[int, set[int]] | None = None,
                        removed_edges: set[frozenset[int]] | None = None
                        ) -> dict[int, int]:
    """SELECT phase: walk `order` (default the observed order), assign each node
    the lowest legal physical. Blockers are the already-assigned physicals of a
    node's interferers (precolored/ghost neighbors always block; virtual
    neighbors block only once assigned earlier in the walk). `extra_neighbors`
    and `removed_edges` apply a what-if perturbation to the graph."""
    order = order if order is not None else ig.select_order
    extra_neighbors = extra_neighbors or {}
    removed = removed_edges or set()
    assigned: dict[int, int] = {}
    dispensed: set[int] = set()
    for idx in order:
        node = ig.nodes.get(idx)
        if node is None:
            continue
        nbrs = set(node.neighbors) | extra_neighbors.get(idx, set())
        blocked: set[int] = set()
        for n in nbrs:
            if frozenset((idx, n)) in removed:
                continue
            if n in node.precolored:
                blocked.add(node.precolored[n])
            elif n in assigned:
                blocked.add(assigned[n])
        # perturbation edges added from the other endpoint
        for n, extra in extra_neighbors.items():
            if idx in extra and frozenset((idx, n)) not in removed:
                if n in assigned:
                    blocked.add(assigned[n])
        pick = _pick(blocked, dispensed)
        assigned[idx] = pick
        if pick in _CALLEE_SET:
            dispensed.add(pick)
    return assigned


@dataclass
class G1Result:
    function: str
    class_id: int
    total: int
    correct: int
    mismatches: list[tuple[int, int, int]]  # (ig_idx, predicted, observed)
    spill_abstained: int

    @property
    def rate(self) -> float:
        return self.correct / self.total if self.total else 1.0


def validate_g1(ig: IG, fn_name: str = "") -> G1Result:
    """Predict assignments at the OBSERVED order and compare to observed regs."""
    pred = predict_assignments(ig)
    total = correct = spill = 0
    mism: list[tuple[int, int, int]] = []
    for idx in ig.select_order:
        node = ig.nodes[idx]
        if node.observed_reg == SPILL or node.incomplete:
            spill += 1
            continue
        total += 1
        if pred.get(idx) == node.observed_reg:
            correct += 1
        else:
            mism.append((idx, pred.get(idx, SPILL), node.observed_reg))
    return G1Result(fn_name, ig.class_id, total, correct, mism, spill)


def gpr_section(events: FunctionEvents) -> ColorgraphSection | None:
    for s in events.colorgraph_sections:
        if s.class_id == 0:
            return s
    return events.colorgraph_sections[0] if events.colorgraph_sections else None


# ---- what-if solver ----

@dataclass
class WhatIf:
    target_ig: int
    observed_reg: int
    predicted_reg: int          # baseline prediction (sanity vs observed)
    perturbed_reg: int          # reg after the perturbation
    flips: bool                 # perturbed_reg != predicted_reg
    description: str


def what_if(ig: IG, target_ig: int, *, add_interferers: set[int] = frozenset(),
            remove_edges: set[frozenset[int]] = frozenset(),
            move_before: int | None = None) -> WhatIf:
    """Predict target_ig's register under a perturbation:
      - add_interferers: ig_idx values to add as neighbors of target_ig
      - remove_edges: {frozenset(a,b)} edges to drop
      - move_before: reorder target_ig to just before this ig_idx in select order
    """
    base = predict_assignments(ig)
    order = list(ig.select_order)
    if move_before is not None and target_ig in order and move_before in order:
        order.remove(target_ig)
        order.insert(order.index(move_before), target_ig)
    extra = {target_ig: set(add_interferers)} if add_interferers else {}
    pert = predict_assignments(ig, order=order, extra_neighbors=extra,
                               removed_edges=set(remove_edges))
    desc_parts = []
    if add_interferers:
        desc_parts.append(f"+interferers {sorted(add_interferers)}")
    if remove_edges:
        desc_parts.append("-edges " + ",".join(
            "/".join(map(str, sorted(e))) for e in remove_edges))
    if move_before is not None:
        desc_parts.append(f"move before ig{move_before}")
    return WhatIf(
        target_ig=target_ig,
        observed_reg=ig.nodes[target_ig].observed_reg if target_ig in ig.nodes else SPILL,
        predicted_reg=base.get(target_ig, SPILL),
        perturbed_reg=pert.get(target_ig, SPILL),
        flips=pert.get(target_ig) != base.get(target_ig),
        description="; ".join(desc_parts) or "no-op")


def load_gpr_ig(pcdump_text: str, fn_name: str) -> IG | None:
    events = find_function(parse_hook_events(pcdump_text), fn_name)
    if events is None:
        return None
    sec = gpr_section(events)
    return build_ig(sec) if sec else None
