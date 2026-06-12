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

    Fields
    ------
    valid           : False if either target role is missing from the reanchor
                      match (identity lost, role coalesced/spilled, or the
                      function was not found in the pcdump).
    invalid_reason  : human-readable reason when valid=False, else None.
    rank33          : 1-based colorgraph position for the REANCHORED ig that
                      maps to original ig33 (role ``y``, param).  None if invalid.
    rank40          : 1-based colorgraph position for the REANCHORED ig that
                      maps to original ig40 (role ``gp``, local).  None if invalid.
    order_distance  : sum |rank - target_rank| for both roles (0 == perfect).
                      Set to None when invalid.
    phys_matched    : count of the two target roles whose assigned_reg matches
                      the desired physical register.  None when invalid.
    """

    valid: bool
    invalid_reason: Optional[str]
    rank33: Optional[int]
    rank40: Optional[int]
    order_distance: Optional[int]
    phys_matched: Optional[int]


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
    """Identity-safe scorer for a mutated-source 9ACC candidate.

    Mutating source can renumber IG nodes.  This function resolves the NEW ig
    numbers that correspond to original ig33 (role ``y``) and ig40 (role
    ``gp``) via ``reanchor_descs``, then reads ranks and assigned registers
    for those REANCHORED nodes.

    Parameters
    ----------
    cand_pcdump_text : pcdump text from compiling the mutated source.
    ref_descs        : ``{ig_idx: RoleDescriptor}`` built from the BASELINE
                       compile (the identity reference).  Obtain with
                       ``build_descriptors(Compile.from_text(...), class_id=0)``.
    function         : function name to look up in the pcdump.
    class_id         : colorgraph class (default 0 = GPR).
    order_target     : override NINEACC_ORDER_TARGET (original ig → desired rank).
    phys_target      : override NINEACC_PHYS_TARGET (original ig → desired phys).
    cand_source      : the mutated C source text for the candidate (used for IR
                       name binding in build_descriptors).  If empty, variable
                       names are not available and identity matching relies only
                       on first_def_sig and use_site_multiset.  For the sweep,
                       pass the actual variant source for best matching quality.

    Returns
    -------
    CandidateScore with valid=False and an ``invalid_reason`` if either target
    role is identity-lost (absent from reanchor.matched).  When valid=True,
    ``rank33``, ``rank40``, ``order_distance``, and ``phys_matched`` are all
    populated using the reanchored ig numbers.
    """
    _order_target = order_target if order_target is not None else NINEACC_ORDER_TARGET
    _phys_target = phys_target if phys_target is not None else NINEACC_PHYS_TARGET

    # Compile, build_descriptors, and reanchor_descs are bound at module level
    # so tests can patch them via "src.search.directed.order_metric.Compile" etc.

    # Build candidate descriptors.
    try:
        cand_compile = Compile.from_text(cand_pcdump_text, function, source=cand_source)
    except (ValueError, Exception) as exc:
        return CandidateScore(
            valid=False,
            invalid_reason=f"compile_parse_failed: {exc}",
            rank33=None,
            rank40=None,
            order_distance=None,
            phys_matched=None,
        )

    cand_descs = build_descriptors(cand_compile, class_id=class_id)

    # Desired phys for the roles we care about (using original ig numbers).
    desired = {orig_ig: phys for orig_ig, phys in _phys_target.items()}

    # Reanchor: map original ig numbers → candidate ig numbers.
    ra = reanchor_descs(ref_descs, cand_descs, desired, class_id=class_id)
    # ra.matched: {new_ig: orig_ig} (round-trip confirmed)

    # Invert to orig_ig -> new_ig.
    orig_to_new: dict[int, int] = {orig: new for new, orig in ra.matched.items()}

    # Check both target roles are reanchored.
    missing_roles = [orig for orig in _order_target if orig not in orig_to_new]
    if missing_roles:
        reason = "identity_lost: orig_ig " + ",".join(str(x) for x in sorted(missing_roles))
        return CandidateScore(
            valid=False,
            invalid_reason=reason,
            rank33=None,
            rank40=None,
            order_distance=None,
            phys_matched=None,
        )

    # Read ranks from candidate pcdump using REANCHORED ig numbers.
    cand_ranks_raw = colorgraph_ranks(cand_pcdump_text, function, class_id=class_id)

    # Build reanchored rank map: original_ig -> rank (using new ig).
    reanchored_ranks: dict[int, int] = {}
    for orig_ig, new_ig in orig_to_new.items():
        if new_ig in cand_ranks_raw:
            reanchored_ranks[orig_ig] = cand_ranks_raw[new_ig]

    # Both roles must appear in the colorgraph section.
    missing_in_graph = [orig for orig in _order_target if orig not in reanchored_ranks]
    if missing_in_graph:
        reason = "role_not_in_colorgraph: orig_ig " + ",".join(
            str(x) for x in sorted(missing_in_graph)
        )
        return CandidateScore(
            valid=False,
            invalid_reason=reason,
            rank33=None,
            rank40=None,
            order_distance=None,
            phys_matched=None,
        )

    # Check for spill (spilled roles are invalid for rank comparison).
    for orig_ig, new_ig in orig_to_new.items():
        if orig_ig in _order_target:
            desc = cand_descs.get(new_ig)
            if desc is not None and desc.spilled:
                return CandidateScore(
                    valid=False,
                    invalid_reason=f"role_spilled: orig_ig {orig_ig}",
                    rank33=None,
                    rank40=None,
                    order_distance=None,
                    phys_matched=None,
                )

    # Compute order_distance using reanchored ranks with the original-ig keys.
    od = order_distance(reanchored_ranks, _order_target)

    # Compute phys_matched using reanchored ig numbers.
    phys_hits = 0
    for orig_ig, desired_reg in _phys_target.items():
        new_ig = orig_to_new.get(orig_ig)
        if new_ig is not None:
            dec_by_ig = {d.ig_idx: d for d in _iter_decisions(cand_pcdump_text, function, class_id)}
            cand_dec = dec_by_ig.get(new_ig)
            if cand_dec is not None and cand_dec.assigned_reg == desired_reg:
                phys_hits += 1

    return CandidateScore(
        valid=True,
        invalid_reason=None,
        rank33=reanchored_ranks.get(33),
        rank40=reanchored_ranks.get(40),
        order_distance=od,
        phys_matched=phys_hits,
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
