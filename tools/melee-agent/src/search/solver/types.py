"""Shared solver dataclasses (surrogate-as-solver, spec §1/§7).

A Perturbation is the single unit the surrogate scores and realize.py maps to a
C move. `kind` selects which optional fields are meaningful:
  node-add  -> target_ig (the value V being split), use_set, new_ig, position,
               interfere_original
  edge-*    -> edge (a, b)
  order     -> order_move ("before"|"after", anchor_ig)
  coalesce  -> target_ig (experimental; spec §1d, NOT in v1 default kinds)

serialize_perturbation emits EXACTLY the spec §7 schema fields
({kind, target_ig, use_set?, edge?, order_move?}); the internal-only fields
(new_ig/position/interfere_original) are retained in memory for apply/gate use
but never serialized into the worksheet.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class PerturbationKind(enum.Enum):
    NODE_ADD = "node-add"
    EDGE_ADD = "edge-add"
    EDGE_REMOVE = "edge-remove"
    ORDER = "order"
    COALESCE = "coalesce"  # experimental; spec §1d, NOT in v1 default kinds


@dataclass(frozen=True)
class Perturbation:
    kind: PerturbationKind
    target_ig: int
    # node-add only:
    use_set: Optional[tuple] = None
    new_ig: Optional[int] = None
    position: Optional[str] = None            # "before" | "after"
    interfere_original: Optional[bool] = None
    # edge-add / edge-remove only:
    edge: Optional[tuple] = None              # (a, b)
    # order only:
    order_move: Optional[tuple] = None        # ("before"|"after", anchor_ig)


def serialize_perturbation(p: Perturbation) -> dict:
    """Spec §7 candidate.perturbation — schema fields only, Nones omitted."""
    d: dict = {"kind": p.kind.value, "target_ig": p.target_ig}
    if p.use_set is not None:
        d["use_set"] = list(p.use_set)
    if p.edge is not None:
        d["edge"] = list(p.edge)
    if p.order_move is not None:
        d["order_move"] = list(p.order_move)
    return d
