"""PRODUCTION probe-signal derivations feeding the §1.5 ProbeContext.

Shared by the calibration gate (frozen pcdump+source artifacts), the CLI live
adapter, and unit tests — ONE derivation path so the filter is never fed
hardcoded-permissive signals (codex blocker 3).

Signal sources:
  is_runtime_value (L2(a))   : V's first-def opcode from explain_virtuals'
                               SourceAttribution.first_def. li/lis -> constant.
                               Unknown -> True (the spec rejects only PROVEN
                               li/lis-defined constants).
  caller_visible_source (b)  : resolved source object is not None (explain-
                               virtual's source can be None: intra-inline /
                               unresolvable -> rejected_b).
  copy_already_survives (c)  : function-level window-shift residual — every
                               phys_target entry maps callee-save -> callee-save
                               with ONE uniform nonzero delta (the CreateStatRow
                               r22-vs-r21 signature). Heuristic, stated as such;
                               the Task-11 calibration gate validates it on the
                               flag_c fixture.
  original_keeps_use_past_vprime (L1): the routed use-set is a PROPER subset of
                               V's modelled uses (neighbor-set proxy); routing
                               ALL uses is coalesce-bait.
"""
from __future__ import annotations

from typing import Optional

from src.mwcc_debug.tiebreak import IG
from src.search.solver.types import Perturbation
from src.search.solver.validity import ProbeContext

_CONST_DEF_OPCODES = {"li", "lis"}
_GPR_CALLEE_SAVES = set(range(13, 32))   # r13-r31
_FPR_CALLEE_SAVES = set(range(14, 32))   # f14-f31


def _callee_saves(class_id: int) -> set:
    return _FPR_CALLEE_SAVES if class_id == 1 else _GPR_CALLEE_SAVES


def is_window_order_residual(ig: IG, phys_target: dict) -> bool:
    """True when the residual is a uniform callee-save window shift: every
    target ig's observed AND desired register is a callee-save, and all
    observed-desired deltas equal one nonzero constant."""
    if not phys_target:
        return False
    saves = _callee_saves(ig.class_id)
    deltas = set()
    for ig_idx, desired in phys_target.items():
        node = ig.nodes.get(int(ig_idx))
        if node is None:
            return False
        observed = node.observed_reg
        if observed not in saves or desired not in saves:
            return False
        deltas.add(observed - desired)
    return len(deltas) == 1 and 0 not in deltas


def source_object_of(report, ig_idx: int) -> Optional[str]:
    """Resolved source object for ig_idx from a VirtualAttributionReport.
    None when the attribution has no source (drives rejected_b / tooling_leads)."""
    for va in getattr(report, "virtuals", ()):
        if getattr(va, "ig_idx", None) == ig_idx:
            src = getattr(va, "source", None)
            if src is None:
                return None
            return getattr(src, "name", None) or getattr(src, "expression", None)
    return None


def first_def_opcode_of(report, ig_idx: int) -> Optional[str]:
    """V's first-def opcode from the same report (None when absent)."""
    for va in getattr(report, "virtuals", ()):
        if getattr(va, "ig_idx", None) == ig_idx:
            src = getattr(va, "source", None)
            fd = getattr(src, "first_def", None) if src is not None else None
            return getattr(fd, "opcode", None) if fd is not None else None
    return None


def derive_probe_context(p: Perturbation, ig: IG, *,
                         first_def_opcode: Optional[str],
                         source_object: Optional[str],
                         window_residual: bool) -> ProbeContext:
    node = ig.nodes.get(p.target_ig)
    uses = set(node.neighbors) if node is not None else set()
    routed = set(p.use_set or ())
    keeps = bool(uses) and routed < uses          # PROPER subset (L1)
    runtime = True
    if first_def_opcode:
        runtime = first_def_opcode.strip().lower() not in _CONST_DEF_OPCODES
    return ProbeContext(
        is_runtime_value=runtime,
        caller_visible_source=source_object is not None,
        copy_already_survives=window_residual,
        original_keeps_use_past_vprime=keeps,
    )
