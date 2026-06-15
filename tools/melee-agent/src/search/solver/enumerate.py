"""§2.1 bounded generators + single/pair enumeration + 200k cap with reserved
per-kind floors (spec §2 steps 3/5, §2.1).

Bounds: implicated_nodes = 1-hop (spike-checked widen-to-2-hop, cap 64);
use_set_family = fixed 4; insertion_positions = 2. Eval cap 200k; edge + order
each reserve a 10k floor (node-add gets >=180k). The advertised kind vocabulary
is {node-add, edge, order}; `edge` NORMALIZES to edge-add + edge-remove (codex
major 6). Filter verdicts are TALLIED (filter_summary counts) and flagged_c
candidates are still EVALUATED into window_order_hits (spec §1.5 (c)).

compose_frontier_pairs is the PRODUCTION pair body (codex blocker 1): apply both
perturbations, predict, record FULL pair hits, charge the remaining global
budget. Pairs fire when NO actionable single exists (finding 3), not zero hits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src.mwcc_debug.tiebreak import IG, predict_assignments
from src.search.solver.perturbations import apply
from src.search.solver.types import Perturbation, PerturbationKind

_ADVERTISED_KINDS = ("node-add", "edge", "order")
_INTERNAL_KINDS = {"node-add", "edge-add", "edge-remove", "order"}


def normalize_kinds(kinds) -> tuple:
    """Expand the advertised vocabulary to internal generator kinds."""
    out: list = []
    for k in kinds:
        k = k.strip()
        if k == "edge":
            out += ["edge-add", "edge-remove"]
        elif k in _INTERNAL_KINDS:
            out.append(k)
        else:
            raise ValueError(f"unknown kind {k!r}; expected "
                             f"{sorted(set(_ADVERTISED_KINDS) | _INTERNAL_KINDS)}")
    return tuple(dict.fromkeys(out))


@dataclass
class EnumConfig:
    eval_cap: int = 200_000
    edge_floor: int = 10_000
    order_floor: int = 10_000
    kinds: tuple = _ADVERTISED_KINDS
    frontier: int = 32                 # F (tunable; spec §2 step 5 / open Q4)
    implicated_hops: int = 1
    implicated_cap: int = 64
    new_ig_base: int = 100_000         # synthetic ig numbers for V'

    def node_add_budget(self) -> int:
        return self.eval_cap - self.edge_floor - self.order_floor


@dataclass
class EnumResult:
    full_hits: list                    # [{perturbation, targets_met, delta, actionable}]
    partial_hits: list
    window_order_hits: list            # flagged_c, EVALUATED (informational)
    filter_counts: dict                # spec §7 filter_summary keys
    evals_per_kind: dict               # {node-add, edge, order} (spec §7)
    truncated: bool
    last_kind: Optional[str]


def implicated_nodes(ig: IG, phys_target: dict, *, hops: int = 1,
                     cap: int = 64) -> set:
    impl = set(int(k) for k in phys_target)
    frontier = set(impl)
    for _ in range(hops):
        nxt = set()
        for ig_idx in frontier:
            node = ig.nodes.get(ig_idx)
            if node:
                nxt |= {n for n in node.neighbors if n in ig.nodes}
        impl |= nxt
        frontier = nxt
        if len(impl) >= cap:
            break
    return set(sorted(impl)[:cap]) if len(impl) > cap else impl


def use_set_family(ig: IG, v: int) -> list:
    """Fixed small family (spec §2.1), approximated from the IG as subsets of
    v's neighbors. Bounded at 4. Includes the all-uses family (it exists in
    source space; the L1 strict-subset rule rejects it as coalesce-bait — that
    reject must be OBSERVABLE in filter_counts, so it is generated)."""
    node = ig.nodes.get(v)
    if node is None:
        return []
    nbrs = sorted(n for n in node.neighbors if n in ig.nodes)
    families = []
    if nbrs:
        families.append(tuple(nbrs))                 # all uses (L1-reject bait)
        families.append((nbrs[0],))                  # single (hottest proxy)
    if len(nbrs) > 1:
        families.append(tuple(nbrs[1:]))             # uses past first
        families.append(tuple(nbrs[:-1]))            # uses before last
    seen, out = set(), []
    for f in families:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
        if len(out) == 4:
            break
    return out


def insertion_positions(ig: IG, v: int) -> list:
    return ["before", "after"]


def _targets_met(assigns: dict, phys_target: dict) -> int:
    return sum(1 for k, want in phys_target.items() if assigns.get(k) == want)


def _delta(base: dict, assigns: dict, phys_target: dict) -> dict:
    return {k: [base.get(k), assigns.get(k)]
            for k in phys_target if base.get(k) != assigns.get(k)}


def enumerate_single(ig: IG, phys_target: dict, *, config: EnumConfig,
                     filter_fn: Callable, probe_ctx_fn: Callable,
                     kinds=_ADVERTISED_KINDS) -> EnumResult:
    """Enumerate single perturbations kind-by-kind in priority order, applying
    the §1.5 filter (node-add only), tallying verdicts, evaluating flagged_c
    candidates into the window bucket. Honors per-kind floors + the global cap."""
    full, partial, window = [], [], []
    counts = {"candidates_generated": 0, "rejected_a": 0, "rejected_b": 0,
              "flagged_c": 0, "rejected_survival": 0}
    evals = {"node-add": 0, "edge": 0, "order": 0}
    budgets = {"node-add": config.node_add_budget(),
               "edge": config.edge_floor, "order": config.order_floor}
    total_target = len(phys_target)
    truncated, last_kind = False, None
    impl = implicated_nodes(ig, phys_target, hops=config.implicated_hops,
                            cap=config.implicated_cap)
    base = predict_assignments(ig)
    next_new = config.new_ig_base

    def _bucket(kind_str):
        return ("node-add" if kind_str == "node-add"
                else "order" if kind_str == "order" else "edge")

    for kind_str in normalize_kinds(kinds):
        last_kind = kind_str
        bucket = _bucket(kind_str)
        kind_truncated = False
        for v in sorted(impl):
            perts: list = []
            if kind_str == "node-add":
                for use_set in use_set_family(ig, v):
                    for pos in insertion_positions(ig, v):
                        perts.append(Perturbation(
                            PerturbationKind.NODE_ADD, target_ig=v,
                            use_set=use_set, new_ig=next_new, position=pos,
                            interfere_original=True))
                        next_new += 1
            elif kind_str in ("edge-add", "edge-remove"):
                k = (PerturbationKind.EDGE_ADD if kind_str == "edge-add"
                     else PerturbationKind.EDGE_REMOVE)
                perts = [Perturbation(k, target_ig=v, edge=(v, o))
                         for o in sorted(impl - {v})]
            else:  # order
                perts = [
                    Perturbation(
                        PerturbationKind.ORDER,
                        target_ig=v,
                        order_move=(position, o),
                    )
                    for o in sorted(impl - {v})
                    for position in ("before", "after")
                ]
            for p in perts:
                counts["candidates_generated"] += 1
                verdict = None
                if p.kind is PerturbationKind.NODE_ADD:
                    verdict = filter_fn(p, probe_ctx_fn(p))
                if verdict is not None and not verdict.admit:
                    if verdict.reason:
                        counts[verdict.reason] += 1
                        continue                      # hard reject: never evaluated
                    if verdict.flag == "flagged_c":
                        counts["flagged_c"] += 1      # quarantine: STILL evaluated
                if evals[bucket] >= budgets[bucket]:
                    # Per-kind budget hit: record truncation and MOVE ON to the
                    # next kind — the reserved floors guarantee edge/order still
                    # run after node-add exhausts its budget (spec §2.1: "the
                    # two 10k floors are then guaranteed regardless of node-add
                    # consumption"). Never abort the whole enumeration here.
                    truncated = True
                    kind_truncated = True
                    break
                try:
                    ig2 = apply(ig, p)
                except Exception:
                    continue
                evals[bucket] += 1
                assigns = predict_assignments(ig2)
                met = _targets_met(assigns, phys_target)
                rec = {"perturbation": p, "targets_met": met,
                       "delta": _delta(base, assigns, phys_target),
                       "actionable": False}
                if verdict is not None and verdict.flag == "flagged_c":
                    window.append(rec)
                elif met >= total_target and total_target > 0:
                    full.append(rec)
                elif met > 0:
                    partial.append(rec)
            if kind_truncated:
                break
        # continue to the next kind regardless (floors guaranteed).
    return EnumResult(full, partial, window, counts, evals, truncated, last_kind)


def compose_frontier_pairs(ig: IG, phys_target: dict, frontier: list,
                           config: EnumConfig, *, evals_used: int) -> dict:
    """PRODUCTION pair composition (codex blocker 1): for each unordered pair of
    frontier entries, apply both perturbations, predict, record FULL pair hits.
    Pair evals charge the REMAINING global budget (eval_cap - evals_used)."""
    budget = max(config.eval_cap - evals_used, 0)
    pair_hits: list = []
    pair_evals = 0
    truncated = budget == 0 and len(frontier) > 1
    total = len(phys_target)
    base = predict_assignments(ig)
    for i in range(len(frontier)):
        if truncated:
            break
        for j in range(i + 1, len(frontier)):
            if pair_evals >= budget:
                truncated = True
                break
            p1 = frontier[i]["perturbation"]
            p2 = frontier[j]["perturbation"]
            if (p1.kind is PerturbationKind.NODE_ADD
                    and p2.kind is PerturbationKind.NODE_ADD
                    and p1.new_ig == p2.new_ig):
                continue                                # synthetic-id collision
            try:
                ig2 = apply(apply(ig, p1), p2)
            except Exception:
                continue
            pair_evals += 1
            assigns = predict_assignments(ig2)
            met = _targets_met(assigns, phys_target)
            if met >= total and total > 0:
                pair_hits.append({
                    "perturbations": (p1, p2), "targets_met": met,
                    "delta": _delta(base, assigns, phys_target),
                    "actionable": False})
    return {"ran": True, "reason": "no actionable single",
            "frontier_size": len(frontier), "frontier": frontier,
            "pair_hits": pair_hits, "pair_evals": pair_evals,
            "truncated": truncated}


def enumerate_with_escalation(ig: IG, phys_target: dict, *, config: EnumConfig,
                              filter_fn: Callable, probe_ctx_fn: Callable,
                              actionable_fn: Callable,
                              _single_impl=enumerate_single,
                              _pair_impl=compose_frontier_pairs) -> dict:
    """Run single enumeration; escalate to PRODUCTION pair composition iff NO
    actionable single exists (finding 3 — a low-confidence/tooling-lead single
    must not suppress pairs)."""
    single = _single_impl(ig, phys_target, config=config, filter_fn=filter_fn,
                          probe_ctx_fn=probe_ctx_fn, kinds=config.kinds)
    if any(actionable_fn(h) for h in single.full_hits):
        return {"single": single,
                "pair_escalation": {"ran": False,
                                    "reason": "actionable single exists",
                                    "frontier_size": 0, "frontier": [],
                                    "pair_hits": [], "pair_evals": 0,
                                    "truncated": False}}
    frontier = sorted(single.partial_hits,
                      key=lambda h: -h["targets_met"])[:config.frontier]
    pair = _pair_impl(ig, phys_target, frontier, config,
                      evals_used=sum(single.evals_per_kind.values()))
    return {"single": single, "pair_escalation": pair}
