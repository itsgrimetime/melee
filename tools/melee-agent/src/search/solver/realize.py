"""Perturbation -> lever-catalog C-realization + assembly into worksheet inputs
(spec §2 step 4, §7; codex major 10 — assemble_realized is production, tested).

Lever priority (spec §2 step 4): node-set (a) > edge (b) > order (c); within
node-set: alias > temp-for-expr > anchoring > per-loop-local > inline-base-cast.
Tie-break: perturbation SIZE then assignment churn (delta count).

A perturbation with NO resolved source object is non-actionable telemetry ->
tooling_leads, never a worksheet candidate (finding 7). Window-flagged evaluated
hits -> window_order rows (informational, never exit-0/apply).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.search.solver.types import Perturbation, serialize_perturbation
from src.search.solver.worksheet import classify_confidence

_NODE_SET_ORDER = ["alias", "temp-for-expr", "anchoring", "per-loop-local",
                   "inline-base-cast"]
_TIER_RANK = {"a": 0, "b": 1, "c": 2}


@dataclass(frozen=True)
class CRealization:
    lever: str
    confidence_tier: str          # "a" | "b" | "c" (spec §7 confidence_tier)
    source_object: Optional[str]
    note: str = ""


@dataclass
class RealizedBundle:
    """assemble_realized output — the worksheet inputs."""
    candidates: list              # actionable, ranked, schema-shaped dicts
    tooling_leads: list
    window_order: list
    filter_summary: dict          # spec §7 filter_summary keys
    evals_per_kind: dict          # {node-add, edge, order}
    pair_escalation: dict         # enriched pair block (incl. pair_hits)
    enumeration_truncated: bool = False
    last_kind: Optional[str] = None


def load_catalog(source) -> dict:
    """kind->levers catalog from an inline dict (unit fixtures) or a directory
    of per-kind JSON files (<kind>.json: [{lever, tier, note}])."""
    if isinstance(source, dict):
        return dict(source)
    cat: dict = {}
    d = Path(source)
    for kind in ("node-add", "edge-add", "edge-remove", "order"):
        f = d / f"{kind}.json"
        if f.exists():
            cat[kind] = json.loads(f.read_text())
    return cat


def realize_perturbation(p: Perturbation, catalog, *,
                         source_object: Optional[str]) -> list:
    """Map a perturbation to C realizations; [] when no source object."""
    if source_object is None:
        return []
    entries = catalog.get(p.kind.value, [])
    reals = [CRealization(e["lever"], e["tier"], source_object, e.get("note", ""))
             for e in entries]
    reals.sort(key=lever_priority_rank)
    return reals


def lever_priority_rank(r: CRealization) -> tuple:
    tier = _TIER_RANK.get(r.confidence_tier, 9)
    within = (_NODE_SET_ORDER.index(r.lever)
              if r.lever in _NODE_SET_ORDER else 99)
    return (tier, within)


def _reals_dicts(reals: list) -> list:
    return [{"lever": r.lever, "source_object": r.source_object,
             "confidence_tier": r.confidence_tier} for r in reals]


def assemble_realized(enum_out: dict, *, phys_target: dict, catalog,
                      source_lookup: Callable[[int], Optional[str]],
                      ) -> RealizedBundle:
    """Turn enumerate_with_escalation output into worksheet inputs.

    Routing: FULL hits with a resolved source object -> ranked candidates;
    FULL hits without -> tooling_leads; window_order_hits -> window_order rows;
    pair_hits enriched with actionability (BOTH ends resolve + realize).
    """
    single = enum_out["single"]
    total = len(phys_target)

    scored: list = []      # (sort_key, candidate_dict)
    leads: list = []
    for hit in single.full_hits:
        p: Perturbation = hit["perturbation"]
        src_obj = source_lookup(p.target_ig)
        reals = realize_perturbation(p, catalog, source_object=src_obj)
        if not reals:
            leads.append({"perturbation": serialize_perturbation(p),
                          "targets_met": hit["targets_met"],
                          "predicted_assignment_delta": hit.get("delta", {}),
                          "note": "no resolved source object (non-actionable)"})
            continue
        best = reals[0]
        conf = classify_confidence(
            full_vector=(total > 0 and hit["targets_met"] >= total),
            has_tier_a_source_object=(best.confidence_tier == "a"
                                      and best.source_object is not None))
        churn = len(hit.get("delta", {}))
        scored.append((
            (lever_priority_rank(best), 1, churn),   # tier, size=1, churn
            {"perturbation": serialize_perturbation(p),
             "predicted_assignment_delta": hit.get("delta", {}),
             "c_realizations": _reals_dicts(reals),
             "surrogate_confidence": conf,
             "fidelity_gate": "pending"},
        ))
    scored.sort(key=lambda t: t[0])
    candidates = []
    for rank, (_key, cand) in enumerate(scored, start=1):
        candidates.append({"rank": rank, **cand})

    window_rows = []
    for hit in single.window_order_hits:
        p = hit["perturbation"]
        window_rows.append({
            "perturbation": serialize_perturbation(p),
            "predicted_assignment_delta": hit.get("delta", {}),
            "residual": "allocation-window",
            "source_object": source_lookup(p.target_ig),
        })

    pe = dict(enum_out["pair_escalation"])
    enriched_pairs = []
    for ph in pe.get("pair_hits", []):
        p1, p2 = ph["perturbations"]
        ok = all(
            realize_perturbation(pp, catalog,
                                 source_object=source_lookup(pp.target_ig))
            for pp in (p1, p2)
        )
        enriched_pairs.append({
            "perturbations": [serialize_perturbation(p1),
                              serialize_perturbation(p2)],
            "targets_met": ph["targets_met"],
            "predicted_assignment_delta": ph.get("delta", {}),
            "actionable": bool(ok),
        })
    pe["pair_hits"] = enriched_pairs    # pair_evals/truncated kept as telemetry

    return RealizedBundle(
        candidates=candidates, tooling_leads=leads, window_order=window_rows,
        filter_summary=dict(single.filter_counts),
        evals_per_kind=dict(single.evals_per_kind),
        pair_escalation=pe,
        enumeration_truncated=single.truncated,
        last_kind=single.last_kind,
    )
