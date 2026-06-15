"""§1.5 enumeration-time validity filter predicate.

Encodes the two corpus-validated upstream laws over a ProbeContext (derived by
probe.py from production signal sources):

  L1 (survival, 8,888-fn corpus): a same-value copy survives iff the original
     retains >=1 genuine use PAST V''s first use (else it provably coalesces).
  L2 (realizability, 3-site probes):
    (a) RUNTIME value, not a li/lis constant (else rematerialized regardless);
    (b) CALLER-VISIBLE split, not intra-inline (else copy-propagated away);
    (c) genuine pressure/interference, NOT an already-surviving copy whose only
        residual is the callee-save window base -> flag-and-quarantine
        (admit=False, flag="flagged_c"; routed to the window_order bucket and
        STILL surrogate-evaluated — data stays visible, never exit-0/apply).

reject/flag strings == spec §7 filter_summary keys:
  rejected_a, rejected_b, flagged_c, rejected_survival.
Non-node-add kinds bypass the filter (the laws are about node-add).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.search.solver.types import Perturbation, PerturbationKind


@dataclass
class ProbeContext:
    is_runtime_value: bool
    caller_visible_source: bool
    copy_already_survives: bool
    original_keeps_use_past_vprime: bool


@dataclass
class FilterVerdict:
    admit: bool
    reason: Optional[str] = None   # rejected_a | rejected_b | rejected_survival
    flag: Optional[str] = None     # flagged_c (window-order quarantine)


def passes_1_5_filter(p: Perturbation, ctx: ProbeContext) -> FilterVerdict:
    if p.kind is not PerturbationKind.NODE_ADD:
        return FilterVerdict(admit=True)
    if not ctx.is_runtime_value:
        return FilterVerdict(admit=False, reason="rejected_a")
    if not ctx.caller_visible_source:
        return FilterVerdict(admit=False, reason="rejected_b")
    if not ctx.original_keeps_use_past_vprime:
        return FilterVerdict(admit=False, reason="rejected_survival")
    if ctx.copy_already_survives:
        return FilterVerdict(admit=False, flag="flagged_c")
    return FilterVerdict(admit=True)
