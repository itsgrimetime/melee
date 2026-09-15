"""Order-distance scorer for the 9ACC directed-search pilot (Phase 0).

Measures how close a compiled candidate's colorgraph color positions are to a
target ordering and target physical register assignments.  The colorgraph
positions are 1-based (rank = iter_idx + 1), matching how the force-iter-first
probe interprets "position 3 / position 5".

Primary entry points:
    colorgraph_ranks            -- {ig_idx: rank} from the last COLORGRAPH DECISIONS
                                   section for a given class in a pcdump.
    order_distance              -- sum-of-absolute-position-deltas to a target dict.
    phys_match                  -- count of ig_idx values whose assigned_reg hits target.
    score_9acc                  -- convenience: build a Score for the 9ACC pilot.
    score_candidate_reanchored  -- identity-safe scorer for mutated-source candidates.

9ACC constants:
    NINEACC_ORDER_TARGET = {40: 3, 33: 5}  -- target 1-based color positions
    NINEACC_PHYS_TARGET  = {33: 27, 40: 29} -- target physical registers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.mwcc_debug.colorgraph_parser import (
    parse_hook_events,
    find_function,
    ColorgraphDecision,
)
from src.mwcc_debug.role_descriptor import Compile, build_descriptors
from src.mwcc_debug.role_reanchor import reanchor_descs

# ---------------------------------------------------------------------------
# 9ACC pilot constants
# ---------------------------------------------------------------------------

# 1-based color positions we want for the two wall nodes.
# Force-iter-first probe proved that ig40@position-3 + ig33@position-5
# produces the desired r27/r29 assignment.
NINEACC_ORDER_TARGET: dict[int, int] = {40: 3, 33: 5}

# Physical registers we want each ig to land on.
NINEACC_PHYS_TARGET: dict[int, int] = {33: 27, 40: 29}

# Penalty added per target ig that is missing from the pcdump (no decision
# found for that ig_idx in the class section).
_MISSING_PENALTY: int = 99


# ---------------------------------------------------------------------------
# Score dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Score:
    """Bundle of Phase-0 scorer outputs for one compiled candidate.

    Fields
    ------
    order_distance        : sum |rank(ig) - target_rank(ig)| for all target igs
                            present in ranks, plus _MISSING_PENALTY for each
                            absent target ig.  0 == perfect order match.
    phys_matched          : count of target igs whose assigned_reg == desired.
    phys_total            : total number of target igs checked (== len(target_phys)).
    rank33                : 1-based color position of ig33, or None if missing.
    rank40                : 1-based color position of ig40, or None if missing.
    missing_target_nodes  : frozenset of target ig_idx values absent from pcdump.
    """

    order_distance: int
    phys_matched: int
    phys_total: int
    rank33: Optional[int]
    rank40: Optional[int]
    missing_target_nodes: frozenset = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def colorgraph_ranks(
    pcdump_text: str,
    function: str,
    class_id: int = 0,
) -> dict[int, int]:
    """Return ``{ig_idx: rank}`` where rank is the 1-based color position.

    Reads the LAST ColorgraphSection for ``function``/``class_id`` in
    ``pcdump_text``.  ``rank = decision.iter_idx + 1`` (iter_idx is
    0-based inside the COLORGRAPH DECISIONS table; the pilot describes
    positions in 1-based terms so we convert here).

    Returns an empty dict if the function or class section is not found.
    """
    events_list = parse_hook_events(pcdump_text)
    fe = find_function(events_list, function)
    if fe is None:
        return {}

    matching = [s for s in fe.colorgraph_sections if s.class_id == class_id]
    if not matching:
        return {}

    section = matching[-1]
    return {d.ig_idx: d.iter_idx + 1 for d in section.decisions}


def order_distance(
    ranks: dict[int, int],
    target: dict[int, int],
) -> int:
    """Return sum of |rank(ig) - target_pos| for all target igs.

    For each ig in *target*:
      - If ig is in *ranks*: add abs(ranks[ig] - target[ig]).
      - If ig is missing from *ranks*: add _MISSING_PENALTY (99).

    A score of 0 means every target ig is at its desired position.
    A score of 4 is the 9ACC baseline (ig33@3, ig40@5 vs target ig40@3, ig33@5).
    """
    total = 0
    for ig, desired_pos in target.items():
        if ig in ranks:
            total += abs(ranks[ig] - desired_pos)
        else:
            total += _MISSING_PENALTY
    return total


def phys_match(
    pcdump_text: str,
    function: str,
    target_phys: dict[int, int],
    class_id: int = 0,
) -> tuple[int, int]:
    """Return ``(matched, total)`` physical register hits.

    For each ig in *target_phys*, checks whether the last colorgraph
    section's ColorgraphDecision.assigned_reg == target_phys[ig].

    Returns ``(matched, total)`` where total == len(target_phys).
    An ig absent from the pcdump counts as a miss (not matched).
    """
    events_list = parse_hook_events(pcdump_text)
    fe = find_function(events_list, function)
    if fe is None:
        return (0, len(target_phys))

    matching = [s for s in fe.colorgraph_sections if s.class_id == class_id]
    if not matching:
        return (0, len(target_phys))

    section = matching[-1]
    decisions_by_ig: dict[int, ColorgraphDecision] = {
        d.ig_idx: d for d in section.decisions
    }

    matched = 0
    for ig, desired_reg in target_phys.items():
        decision = decisions_by_ig.get(ig)
        if decision is not None and decision.assigned_reg == desired_reg:
            matched += 1

    return (matched, len(target_phys))


def score_9acc(pcdump_text: str, class_id: int = 0) -> Score:
    """Convenience scorer for the 9ACC pilot.

    Computes all Score fields for ``grIceMt_801F9ACC`` using the module-level
    ``NINEACC_ORDER_TARGET`` and ``NINEACC_PHYS_TARGET`` constants.
    """
    function = "grIceMt_801F9ACC"
    ranks = colorgraph_ranks(pcdump_text, function, class_id=class_id)

    missing: set[int] = {
        ig for ig in NINEACC_ORDER_TARGET if ig not in ranks
    }

    od = order_distance(ranks, NINEACC_ORDER_TARGET)
    matched, total = phys_match(
        pcdump_text, function, NINEACC_PHYS_TARGET, class_id=class_id
    )

    return Score(
        order_distance=od,
        phys_matched=matched,
        phys_total=total,
        rank33=ranks.get(33),
        rank40=ranks.get(40),
        missing_target_nodes=frozenset(missing),
    )


# ---------------------------------------------------------------------------
# Identity-safe candidate scorer (Phase 1 sweep)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateScore:
    """Result of score_candidate_reanchored for one mutated-source compile.

    Generalized (order-distance directed search, T5) to an arbitrary target-role
    set.  ``ranks_by_role`` maps each original target ig to its 1-based rank in
    the candidate's (reanchored) coloring.  ``order_distance`` is the role-matched
    Kendall pairwise-inversion distance vs the target order (0 == every pair in
    target relative order).  ``coverage`` is the fraction of target roles that
    round-trip-reanchored.

    §3.3 validity: a candidate is ``valid`` iff coverage == 1.0 over the target
    roles AND >= 2 roles anchored.  Otherwise ``valid=False`` with
    ``invalid_reason="target_role_lost"`` — losing a target role can NEVER look
    like progress (closes the test_metric.py:32 hollowing hole at the objective).

    Back-compat: ``rank33``/``rank40`` remain populated for the 9ACC two-role
    pilot so older callers/tests keep working.
    """

    valid: bool
    invalid_reason: Optional[str]
    ranks_by_role: Optional[dict]
    order_distance: Optional[int]
    phys_matched: Optional[int]
    coverage: Optional[float]
    # --- 9ACC back-compat shims ---
    rank33: Optional[int] = None
    rank40: Optional[int] = None


def score_candidate_reanchored(
    cand_pcdump_text: str,
    ref_descs: dict,
    *,
    function: str = "grIceMt_801F9ACC",
    class_id: int = 0,
    order_target: Optional[dict] = None,
    phys_target: Optional[dict] = None,
    cand_source: str = "",
) -> CandidateScore:
    """Identity-safe order-distance scorer for a mutated-source candidate.

    Mutating source can renumber IG nodes.  This resolves each target role's NEW
    ig via ``reanchor_descs``, reads ranks/assignments at the reanchored nodes,
    and computes the role-matched Kendall ``order_distance`` vs ``order_target``.

    §3.3 validity (the objective rule): every target role must round-trip-
    reanchor (coverage == 1.0) AND >= 2 roles must anchor, else the candidate is
    ``valid=False, invalid_reason="target_role_lost"`` — never ranked, never 0.

    This is the SHARED scoring core used by the scorer's order branch (T4) and
    the kill-switch harness (T7), so both exercise the same path.
    """
    from src.search.directed.metric import order_distance as kendall_distance

    _order_target = order_target if order_target is not None else NINEACC_ORDER_TARGET
    _phys_target = phys_target if phys_target is not None else NINEACC_PHYS_TARGET

    def _invalid(reason: str) -> CandidateScore:
        return CandidateScore(
            valid=False, invalid_reason=reason, ranks_by_role=None,
            order_distance=None, phys_matched=None, coverage=None,
            rank33=None, rank40=None,
        )

    try:
        cand_compile = Compile.from_text(cand_pcdump_text, function, source=cand_source)
    except Exception as exc:
        return _invalid(f"compile_parse_failed: {exc}")

    cand_descs = build_descriptors(cand_compile, class_id=class_id)
    desired = {orig_ig: phys for orig_ig, phys in _phys_target.items()}
    ra = reanchor_descs(ref_descs, cand_descs, desired, class_id=class_id)
    orig_to_new: dict[int, int] = {orig: new for new, orig in ra.matched.items()}

    # §3.3 coverage: every target role must round-trip-reanchor.
    target_igs = list(_order_target)
    anchored = [ig for ig in target_igs if ig in orig_to_new]
    coverage = len(anchored) / len(target_igs) if target_igs else 0.0
    if coverage < 1.0 or len(anchored) < 2:
        return _invalid("target_role_lost")

    # Read ranks at the reanchored ig numbers.
    cand_ranks_raw = colorgraph_ranks(cand_pcdump_text, function, class_id=class_id)
    ranks_by_role: dict[int, int] = {}
    for orig_ig, new_ig in orig_to_new.items():
        if orig_ig in _order_target and new_ig in cand_ranks_raw:
            ranks_by_role[orig_ig] = cand_ranks_raw[new_ig]

    # A target role that reanchored but is absent from the colorgraph (spilled
    # out of the decision set) breaks coverage just like a lost role.
    if len([ig for ig in target_igs if ig in ranks_by_role]) < len(target_igs):
        return _invalid("target_role_lost")
    for orig_ig in target_igs:
        desc = cand_descs.get(orig_to_new[orig_ig])
        if desc is not None and desc.spilled:
            return _invalid("target_role_lost")

    # Role-matched Kendall distance: build cand/objective iter maps keyed by the
    # ORIGINAL ig (ranks are 1-based positions; relative order is what Kendall
    # consumes, so using ranks directly is equivalent to using iter_idx).
    od = kendall_distance(ranks_by_role, _order_target)

    # Phys hits at reanchored igs.
    phys_hits = 0
    dec_by_ig = {d.ig_idx: d for d in _iter_decisions(cand_pcdump_text, function, class_id)}
    for orig_ig, desired_reg in _phys_target.items():
        new_ig = orig_to_new.get(orig_ig)
        dec = dec_by_ig.get(new_ig) if new_ig is not None else None
        if dec is not None and dec.assigned_reg == desired_reg:
            phys_hits += 1

    return CandidateScore(
        valid=True, invalid_reason=None, ranks_by_role=ranks_by_role,
        order_distance=od, phys_matched=phys_hits, coverage=coverage,
        rank33=ranks_by_role.get(33), rank40=ranks_by_role.get(40),
    )


def _iter_decisions(pcdump_text: str, function: str, class_id: int = 0):
    """Yield ColorgraphDecision objects for the last class section of function."""
    events_list = parse_hook_events(pcdump_text)
    fe = find_function(events_list, function)
    if fe is None:
        return
    matching = [s for s in fe.colorgraph_sections if s.class_id == class_id]
    if not matching:
        return
    yield from matching[-1].decisions
