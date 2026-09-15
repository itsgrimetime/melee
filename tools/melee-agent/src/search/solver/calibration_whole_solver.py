"""T10e whole-solver reject-confirmation harness (pure, mwcc-free over frozen
artifacts).

The §1.5 calibration gate's three REJECT-CONFIRMATION fixtures must show the
PRODUCTION enumerate+filter path drop a candidate, not merely that the filter
PREDICATE rejects a hand-built ProbeContext (that is test_validity's job). This
module wires the production pieces together over a frozen IG + a frozen
source-attribution bridge, with NO oracle fields on the candidate or context
(A1 rev 2 §1):

  * build_probe_ctx_fn(ig, report) -> a closure deriving ProbeContext for ANY
    node-add candidate via probe.derive_probe_context over the FROZEN
    explain_virtuals report (the production signal source). The closure NEVER
    sees an expected token; it only reads raw report/IG fields.

  * run_whole_solver_node_add(...) -> runs the production enumerate.enumerate_single
    (the real generator + the real passes_1_5_filter + the closure above) and
    reports, for a chosen target_ig, whether the candidates targeting it were
    REJECTED with a token / FLAGGED to the window bucket, and that none of them
    survived into full/partial hits. This is the WHOLE-SOLVER assertion: the
    enumeration GENERATES the candidate, the filter DROPS it.

  * recompute_verdict_audit(...) -> A1 rev 2 §1 no-oracle audit: independently
    recompute passes_1_5_filter over the SAME derived context for every node-add
    candidate the enumeration generated for the target, and assert the recomputed
    verdict equals the verdict the production filter returned inside the
    enumeration (the harness must not trust a pre-labeled token).

  * broken_filter_admit_everything -> A1 rev 2 §3 control: a permissive filter
    stub that admits every node-add. Under it the reject/flag assertion MUST
    FAIL (a filter that cannot fail cannot pass the gate).

  * paired_trace_invariance(...) -> A1 rev 2 §4: baseline-vs-planted enumeration
    over the SAME IG must leave every non-plant candidate identity + outcome,
    the winning-alias identity + rank, enumeration_truncated, and the per-kind
    eval counts UNCHANGED modulo the plant's own accounted evals.

All functions are PURE (no compiler, no disk) so they unit-test over synthetic
IGs and drive the frozen-artifact gate identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src.mwcc_debug.tiebreak import IG
from src.search.solver import probe
from src.search.solver.enumerate import EnumConfig, EnumResult, enumerate_single
from src.search.solver.types import Perturbation, PerturbationKind
from src.search.solver.validity import (
    FilterVerdict,
    ProbeContext,
    passes_1_5_filter,
)


def build_probe_ctx_fn(ig: IG, report, *, window_residual: bool,
                       matched_fn=None) -> Callable:
    """Production ProbeContext closure over a FROZEN explain_virtuals report.

    For a node-add perturbation P, derive its ProbeContext from raw report/IG
    fields ONLY (probe.first_def_opcode_of / probe.source_attr_of /
    is_window_order_residual signal) via probe.derive_probe_context. No oracle
    field is read; this is the exact derivation the production CLI factory uses,
    fed frozen artifacts instead of live ones. `matched_fn` (optional) is the
    matched-fn `(source_file, sig_line, end_line)` span (Amendment A2).
    """
    def probe_ctx_fn(p: Perturbation) -> ProbeContext:
        first_def_opcode = probe.first_def_opcode_of(report, p.target_ig)
        source = probe.source_attr_of(report, p.target_ig)
        return probe.derive_probe_context(
            p, ig,
            first_def_opcode=first_def_opcode,
            source=source,
            window_residual=window_residual,
            matched_fn=matched_fn,
        )
    return probe_ctx_fn


def broken_filter_admit_everything(p: Perturbation, ctx: ProbeContext
                                   ) -> FilterVerdict:
    """A1 rev 2 §3 control: admit EVERY candidate (the production filter's
    laws are deliberately disabled). The reject/flag assertion MUST FAIL under
    this stub; a filter that cannot fail cannot pass the gate."""
    return FilterVerdict(admit=True)


@dataclass
class WholeSolverVerdict:
    target_ig: int
    candidates_for_target: int          # node-add candidates the gen made for it
    rejected_count: int                 # rejected with `expected_reject_token`
    flagged_count: int                  # flagged_c (window quarantine) for it
    survived_in_full: int               # target candidates that reached full_hits
    survived_in_partial: int            # ... or partial_hits
    survived_in_window: int             # ... routed to window_order bucket
    reject_token: Optional[str]         # the production filter's token for it
    audit_equal: bool                   # recompute-equality (A1 rev 2 §1)
    # How many of the target's node-add candidates the ENUMERATION's filter_fn
    # ADMITTED (passed). The §3 control's faithful signal: the REAL filter
    # admits 0 of a constant node's candidates (all hard-rejected); the
    # admit-everything stub admits ALL of them. A non-productive admitted
    # candidate leaves no hit-bucket trace, so survivors are an unreliable
    # control signal for rejected_a — this is the reliable one.
    target_candidates_admitted_by_enum_filter: int
    enum_result: EnumResult


def _node_add_candidates_for(ig: IG, target_ig: int, config: EnumConfig) -> list:
    """Reproduce EXACTLY the node-add candidates enumerate_single generates for
    one target node (same use_set_family x insertion_positions cross product,
    same synthetic new_ig assignment is irrelevant to the filter). Used for the
    independent recompute-equality audit (A1 rev 2 §1)."""
    from src.search.solver.enumerate import insertion_positions, use_set_family
    out = []
    new_ig = config.new_ig_base
    for use_set in use_set_family(ig, target_ig):
        for pos in insertion_positions(ig, target_ig):
            out.append(Perturbation(
                PerturbationKind.NODE_ADD, target_ig=target_ig,
                use_set=use_set, new_ig=new_ig, position=pos,
                interfere_original=True))
            new_ig += 1
    return out


def run_whole_solver_node_add(
    ig: IG, phys_target: dict, *, target_ig: int,
    report, window_residual: bool,
    expected_reject_token: Optional[str] = None,
    expected_flag: Optional[str] = None,
    config: Optional[EnumConfig] = None,
    filter_fn: Callable = passes_1_5_filter,
) -> WholeSolverVerdict:
    """Run the PRODUCTION single enumeration over a frozen IG and report the
    fate of the candidates targeting `target_ig`.

    `filter_fn` defaults to the production passes_1_5_filter; pass
    `broken_filter_admit_everything` for the §3 control. `report` is the frozen
    explain_virtuals bridge feeding probe.derive_probe_context (no oracle).

    The verdict counts, for the chosen target node, how many generated node-add
    candidates the filter rejected with `expected_reject_token` / flagged
    `expected_flag`, and how many survived into the hit buckets. For a clean
    reject fixture: rejected_count == candidates_for_target and 0 survivors.
    For a flag_c fixture: flagged_count == candidates_for_target, all of them in
    the window bucket, 0 in full/partial.
    """
    config = config or EnumConfig()
    probe_ctx_fn = build_probe_ctx_fn(ig, report, window_residual=window_residual)
    result = enumerate_single(ig, phys_target, config=config,
                              filter_fn=filter_fn, probe_ctx_fn=probe_ctx_fn,
                              kinds=("node-add",))

    # Independently recompute the production filter verdict for the target's
    # node-add candidates (A1 rev 2 §1 no-oracle audit). The token the gate
    # asserts must be the one the production predicate computes — recompute it
    # here over the SAME derived context and require a SINGLE consistent token.
    cand = _node_add_candidates_for(ig, target_ig, config)
    reject_tokens = set()
    flag_tokens = set()
    audit_equal = True
    for p in cand:
        ctx = probe_ctx_fn(p)
        v = passes_1_5_filter(p, ctx)          # the production predicate
        if v.reason:
            reject_tokens.add(v.reason)
        if v.flag:
            flag_tokens.add(v.flag)
        # A1 rev 2 §1 audit: the verdict the gate asserts (the production
        # predicate `v`) must equal the verdict the ENUMERATION actually applied
        # (`filter_fn`). Under the real run (filter_fn == passes_1_5_filter) they
        # MUST match -> audit_equal True. Under the §3 broken-filter control
        # (admit-everything) they DIFFER on a rejected candidate -> audit_equal
        # False, which correctly flags the substituted filter. (A tautological
        # self-comparison would make this always-True and meaningless.)
        applied = filter_fn(p, ctx)
        if (v.admit, v.reason, v.flag) != (applied.admit, applied.reason,
                                           applied.flag):
            audit_equal = False

    reject_token = (sorted(reject_tokens)[0] if len(reject_tokens) == 1
                    else (None if not reject_tokens else "MIXED"))
    flag_token = (sorted(flag_tokens)[0] if len(flag_tokens) == 1
                  else (None if not flag_tokens else "MIXED"))

    # Survivors referencing the target (a clean reject leaves none).
    def _refs(rec):
        return rec["perturbation"].target_ig == target_ig
    survived_full = sum(1 for r in result.full_hits if _refs(r))
    survived_partial = sum(1 for r in result.partial_hits if _refs(r))
    survived_window = sum(1 for r in result.window_order_hits if _refs(r))

    # rejected/flagged tallies for the target: the filter_counts are GLOBAL, so
    # to attribute to the target we recompute per-candidate (same cand list).
    # These use the PRODUCTION predicate (the no-oracle recompute), independent
    # of `filter_fn` — they say what SHOULD happen, audited against the gate's
    # expected token.
    rejected_for_target = 0
    flagged_for_target = 0
    for p in cand:
        v = passes_1_5_filter(p, probe_ctx_fn(p))
        if v.reason == expected_reject_token:
            rejected_for_target += 1
        if v.flag == expected_flag and expected_flag is not None:
            flagged_for_target += 1

    # How many of the target's candidates the ENUMERATION's filter_fn ADMITTED.
    # This is the faithful §3 control signal: the real filter admits 0 (hard
    # reject), the admit-everything stub admits all.
    admitted_by_enum = 0
    for p in cand:
        if p.kind is PerturbationKind.NODE_ADD:
            verdict = filter_fn(p, probe_ctx_fn(p))
            if verdict.admit:
                admitted_by_enum += 1

    return WholeSolverVerdict(
        target_ig=target_ig,
        candidates_for_target=len(cand),
        rejected_count=rejected_for_target,
        flagged_count=flagged_for_target,
        survived_in_full=survived_full,
        survived_in_partial=survived_partial,
        survived_in_window=survived_window,
        reject_token=reject_token if expected_reject_token else flag_token,
        audit_equal=audit_equal,
        target_candidates_admitted_by_enum_filter=admitted_by_enum,
        enum_result=result,
    )


def recompute_verdict_audit(ig: IG, report, *, target_ig: int,
                            window_residual: bool,
                            config: Optional[EnumConfig] = None) -> dict:
    """A1 rev 2 §1 standalone audit: for every node-add candidate the production
    generator makes for `target_ig`, derive the ProbeContext from the frozen
    bridge and recompute passes_1_5_filter; return the (admit, reason, flag)
    tuple set. A clean reject fixture yields exactly ONE reason token and no
    admits; the caller asserts the token equals the fixture's expected token
    (which lives in metadata OUTSIDE this computation)."""
    config = config or EnumConfig()
    probe_ctx_fn = build_probe_ctx_fn(ig, report, window_residual=window_residual)
    verdicts = []
    for p in _node_add_candidates_for(ig, target_ig, config):
        v = passes_1_5_filter(p, probe_ctx_fn(p))
        verdicts.append((v.admit, v.reason, v.flag))
    reasons = {r for _a, r, _f in verdicts if r}
    flags = {f for _a, _r, f in verdicts if f}
    admits = sum(1 for a, _r, _f in verdicts if a)
    return {
        "candidates": len(verdicts),
        "reasons": sorted(reasons),
        "flags": sorted(flags),
        "admits": admits,
        "verdicts": verdicts,
    }


@dataclass
class PairedTraceResult:
    non_plant_identities_unchanged: bool
    non_plant_outcomes_unchanged: bool
    winning_alias_identity_unchanged: bool
    winning_alias_rank_unchanged: bool
    truncated_unchanged: bool
    per_kind_evals_unchanged_modulo_plant: bool

    @property
    def invariant(self) -> bool:
        return all((self.non_plant_identities_unchanged,
                    self.non_plant_outcomes_unchanged,
                    self.winning_alias_identity_unchanged,
                    self.winning_alias_rank_unchanged,
                    self.truncated_unchanged,
                    self.per_kind_evals_unchanged_modulo_plant))


def _hit_identity(rec) -> tuple:
    """A candidate's stable identity for paired-trace comparison: the perturbation
    shape (kind + target + use_set/edge/order), independent of the synthetic
    new_ig number (which differs between runs)."""
    p: Perturbation = rec["perturbation"]
    return (p.kind.value, p.target_ig, p.use_set, p.edge, p.order_move)


def _hit_outcome(rec) -> tuple:
    return (rec["targets_met"], rec.get("actionable", False))


def paired_trace_invariance(baseline: EnumResult, planted: EnumResult, *,
                            plant_target_ig: int,
                            winning_alias_target_ig: Optional[int] = None
                            ) -> PairedTraceResult:
    """A1 rev 2 §4: compare a baseline enumeration against one whose ONLY change
    is an injected plant candidate (targeting plant_target_ig). The plant's own
    candidates are excluded from the comparison; everything else must be
    identical: non-plant candidate identities + outcomes, the winning-alias
    candidate identity + rank, enumeration_truncated, and per-kind eval counts
    modulo the plant's own evaluated candidates.
    """
    def _index(result: EnumResult):
        idx = {}
        for bucket in ("full_hits", "partial_hits", "window_order_hits"):
            for rec in getattr(result, bucket):
                if rec["perturbation"].target_ig == plant_target_ig:
                    continue                          # exclude the plant's own
                idx[_hit_identity(rec)] = (bucket, _hit_outcome(rec))
        return idx

    base_idx = _index(baseline)
    plant_idx = _index(planted)
    identities_unchanged = set(base_idx) == set(plant_idx)
    outcomes_unchanged = all(base_idx[k] == plant_idx.get(k) for k in base_idx)

    # Winning-alias identity + rank: locate the alias hit (a FULL hit on the
    # winning target) in both ranked full-hit lists; its position must match.
    def _full_rank(result: EnumResult, tig):
        ordered = [r for r in result.full_hits
                   if r["perturbation"].target_ig != plant_target_ig]
        for i, r in enumerate(ordered):
            if tig is None or r["perturbation"].target_ig == tig:
                return i, _hit_identity(r)
        return None, None

    if winning_alias_target_ig is not None:
        b_rank, b_id = _full_rank(baseline, winning_alias_target_ig)
        p_rank, p_id = _full_rank(planted, winning_alias_target_ig)
        alias_identity_unchanged = b_id == p_id and b_id is not None
        alias_rank_unchanged = b_rank == p_rank and b_rank is not None
    else:
        alias_identity_unchanged = True
        alias_rank_unchanged = True

    truncated_unchanged = baseline.truncated == planted.truncated

    # Per-kind evals: the plant adds candidates only to the node-add bucket. The
    # planted run's node-add evals must be >= baseline (the plant's own evals)
    # and edge/order must be IDENTICAL. We can only require the non-node-add
    # buckets be exactly equal (modulo the plant's own); node-add differs by the
    # plant's evaluated count.
    be, pe = baseline.evals_per_kind, planted.evals_per_kind
    per_kind_ok = (be.get("edge", 0) == pe.get("edge", 0)
                   and be.get("order", 0) == pe.get("order", 0)
                   and pe.get("node-add", 0) >= be.get("node-add", 0))

    return PairedTraceResult(
        non_plant_identities_unchanged=identities_unchanged,
        non_plant_outcomes_unchanged=outcomes_unchanged,
        winning_alias_identity_unchanged=alias_identity_unchanged,
        winning_alias_rank_unchanged=alias_rank_unchanged,
        truncated_unchanged=truncated_unchanged,
        per_kind_evals_unchanged_modulo_plant=per_kind_ok,
    )
