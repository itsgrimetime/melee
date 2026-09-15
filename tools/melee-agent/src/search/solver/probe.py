"""PRODUCTION probe-signal derivations feeding the §1.5 ProbeContext.

Shared by the calibration gate (frozen pcdump+source artifacts), the CLI live
adapter, and unit tests — ONE derivation path so the filter is never fed
hardcoded-permissive signals (codex blocker 3).

Signal sources:
  is_runtime_value (L2(a))   : V's first-def opcode from explain_virtuals'
                               SourceAttribution.first_def. li/lis -> constant.
                               Unknown -> True (the spec rejects only PROVEN
                               li/lis-defined constants).
  caller_visible_source (b)  : provenance KIND of V's source attribution
                               (Amendment A2). The OLD `source is not None`
                               signal was DEAD — every real traced node carries
                               an expression, so it never rejected. The CORRECT
                               signal: a node is caller-INVISIBLE (-> rejected_b)
                               iff it is a compiler-synthesized intermediate with
                               NO source-level variable (implicit-temp /
                               copy-coalesce-product / a nameless+lineless
                               first-def) or has no source attribution at all.
                               Named param/local/call-return bindings AND
                               field-loads (field-access aliases are realizable
                               via temp introduction) are caller-visible. A bare
                               source_line range is NOT used as a reject trigger:
                               explain_virtuals threads one TU source_file into
                               every node and source_line is a grep heuristic
                               that misattributes in-body locals/params/calls to
                               sibling occurrences (false rejections). KIND has
                               no such imprecision. See Amendment A2.
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

# Amendment A2: provenance KINDs that are compiler-synthesized intermediates with
# NO source-level variable -> no caller-level C expression an alias can split ->
# caller-invisible (rejected_b). Derived from the first-def opcode in
# virtual_attribution._source_from_first_def (mr -> copy/coalesce-product;
# addi/rlwinm/etc -> implicit-temp). A `first-def` KIND with neither a name nor a
# source_line is the same no-source-variable class (li/lis constants are caught
# by L2(a) before L2(b); the residual first-defs are nameless temps).
_SYNTHETIC_NO_SOURCE_KINDS = {"implicit-temp", "copy/coalesce-product"}


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


def source_attr_of(report, ig_idx: int):
    """Raw SourceAttribution for ig_idx from a VirtualAttributionReport (or None).

    This is the object the Amendment-A2 caller-visibility predicate reads
    (kind / name / source_file / source_line). Distinct from source_object_of,
    which flattens it to a display string for tooling_leads naming."""
    for va in getattr(report, "virtuals", ()):
        if getattr(va, "ig_idx", None) == ig_idx:
            return getattr(va, "source", None)
    return None


def source_object_of(report, ig_idx: int) -> Optional[str]:
    """Resolved source DISPLAY object for ig_idx (name or expression), or None.

    Retained for tooling_leads naming / diagnostics. NOTE (Amendment A2): this is
    NO LONGER the caller-visibility signal — `source_object is not None` was the
    dead L2(b) branch (every real node has an expression). Use
    caller_visible_source_of for the filter verdict."""
    src = source_attr_of(report, ig_idx)
    if src is None:
        return None
    return getattr(src, "name", None) or getattr(src, "expression", None)


def caller_visible_source_of(source, *, matched_fn: Optional[tuple] = None
                             ) -> bool:
    """Amendment A2: is V's source a caller-level split point (caller-VISIBLE),
    or a compiler-synthesized intermediate with no C boundary (-> rejected_b)?

    `source` is the RAW SourceAttribution (or None). `matched_fn`, when supplied,
    is the matched function's `(source_file, sig_line, end_line)` provenance span
    — currently recorded for diagnostics / a future tightened in-span ADMIT; the
    v1 REJECT decision rests on the provenance KIND, which is line-imprecision
    immune (see module docstring + Amendment A2).

    Caller-INVISIBLE (returns False -> rejected_b) iff:
      * source is None (no attribution at all — no source variable), OR
      * kind is a synthetic no-source intermediate (implicit-temp /
        copy/coalesce-product), OR
      * kind == first-def with NO name AND no source_line (a nameless temp; note
        li/lis constants are filtered by L2(a) before L2(b)).
    Everything else is caller-VISIBLE: named param/local/call-return bindings (the
    win levers) AND field-loads (field-access aliases are realizable via temp
    introduction — A2 forbids a `name is None` reject). Conservatively admitting
    an ambiguous genuinely-inlinee field-load cannot cause a false win (it must
    still pass the surrogate + the §3 re-extraction gate); rejecting a realizable
    alias would break a win, so soundness (zero false reject) wins.
    """
    if source is None:
        return False
    kind = getattr(source, "kind", None)
    if kind in _SYNTHETIC_NO_SOURCE_KINDS:
        return False
    if kind == "first-def":
        name = getattr(source, "name", None)
        line = getattr(source, "source_line", None)
        if name is None and line is None:
            return False
    return True


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
                         source,
                         window_residual: bool,
                         matched_fn: Optional[tuple] = None) -> ProbeContext:
    """Derive the §1.5 ProbeContext for perturbation `p`.

    `source` is the RAW SourceAttribution for V (or None) — Amendment A2 reads its
    provenance KIND for caller-visibility. `matched_fn` is the optional matched-fn
    `(source_file, sig_line, end_line)` span (diagnostics / future ADMIT
    tightening)."""
    node = ig.nodes.get(p.target_ig)
    uses = set(node.neighbors) if node is not None else set()
    routed = set(p.use_set or ())
    keeps = bool(uses) and routed < uses          # PROPER subset (L1)
    runtime = True
    if first_def_opcode:
        runtime = first_def_opcode.strip().lower() not in _CONST_DEF_OPCODES
    return ProbeContext(
        is_runtime_value=runtime,
        caller_visible_source=caller_visible_source_of(source,
                                                       matched_fn=matched_fn),
        copy_already_survives=window_residual,
        original_keeps_use_past_vprime=keeps,
    )
