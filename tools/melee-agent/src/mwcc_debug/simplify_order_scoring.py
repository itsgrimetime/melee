"""Lexicographically-encoded score for the simplify-order permuter scorer.

The MVP custom-scorer story (see `docs/mwcc-debug-diff-roadmap.md` #3
deep version): we want decomp-permuter to save candidates that improve
our combined simplify-order + precolor metric, regardless of whether they
improve match%. Permuter's default scorer is hardcoded around objdump-
based asm diffing; the only injection point is `objdump_command`. The
CLI command `debug target score-simplify-order` is the integer-scoring
entry point that an objdump-wrapper script will call (the wrapper
transduces the integer back into synthetic objdump output that
permuter's default scorer counts).

This module is the *score computation*: spec loader + the lex-encoded
score function. The wrapper script and CLI command live elsewhere; this
file stays pure-Python with no I/O beyond the YAML spec read.

Score encoding (lex, lower is better):

    score = (target_len - common_prefix_length) * LEX_BIG + distance.total

Properties:
- score == 0 iff prefix == target_len AND distance.total == 0
  (the "perfect candidate")
- Within the same prefix level, distance.total breaks ties continuously
- Across prefix levels, the LEX_BIG factor guarantees that ANY
  prefix=k+1 candidate ranks above EVERY prefix=k candidate, no matter
  how large the distance, so target-hit candidates are never buried
  under low-distance prefix-misses

Why lex (and not the combined α-weighted score from
`simplify_search.combined_value`): permuter's scoring is a single int
that must be monotonically minimized. The lex encoding has no tunable α
that needs calibration to the distribution of distances permuter
produces — campaigns 3 and 4 burned a lot of cycles on α retuning and
that's exactly the trap we don't want at the permuter-integration layer.
The campaign's `--rank-mode lex` flag (shipped in #1.8) already uses
the same lex sort key; this module is the integer encoding of it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Mapping, Optional

from .colorgraph_parser import find_function, parse_hook_events
from .colorgraph_parser import FunctionEvents
from .simplify_search import (
    BaselineSignature,
    PrecolorDistance,
    SimplifyScore,
    baseline_signature,
    precolor_distance,
    score_simplify_order,
)


# Caller-save register threshold for --want-first polarity.
#
# MWCC's volatile dispense (from workingMask = r3..r12 - interferers) picks
# the LOWEST set bit. For target ig_idx values at simplify positions 0/1/...
# to land on a specific high volatile (r10/r11/r12), all lower volatiles
# (r3-r9) would need to be unavailable — which can't happen at position 0
# in a fresh dispense state. So target physicals in this range mean the
# target ig_idx values need LATE simplify positions, not early ones,
# making --want-first the wrong polarity.
#
# r4-r9 are flagged as UNCERTAIN: they may be reachable if other virtuals
# consume r3 first, but it's not guaranteed.
#
# Non-volatiles (r25-r31) are dispensed top-down from r31 by
# obtain_nonvolatile_register, so they're always safe for --want-first.
# r3 is the lowest workingMask bit, so position 0 naturally lands there.
HIGH_VOLATILE_REGS: frozenset[int] = frozenset({10, 11, 12})
UNCERTAIN_VOLATILE_REGS: frozenset[int] = frozenset({4, 5, 6, 7, 8, 9})

# Top-down non-volatile dispense order from obtain_nonvolatile_register.
# These are the first non-volatiles MWCC dispenses to virtuals that need
# a callee-save. For target_position="late", target physicals in this set
# are the WRONG polarity — they go to virtuals processed EARLY in the
# colorgraph, but --want-late puts target ig_idx at the END.
TOP_NON_VOLATILE_REGS: frozenset[int] = frozenset({28, 29, 30, 31})


class Polarity(enum.Enum):
    """Classification of whether the target syntax matches the dispense direction."""

    SAFE = "safe"
    """All target physicals reachable from the chosen simplify-order end."""

    UNCERTAIN = "uncertain"
    """At least one target physical is a mid-volatile (r4-r9); may or
    may not be reachable depending on interference state."""

    WRONG_POLARITY = "wrong_polarity"
    """At least one target physical structurally cannot match the chosen
    target_position. For target_position="first": HIGH_VOLATILE_REGS
    (r10-r12). For target_position="late": TOP_NON_VOLATILE_REGS
    (r28-r31) or r3. lbDvd_80018A2C campaign documented the "first" case."""


def classify_polarity(
    force_phys: Mapping[int, int],
    *,
    target_position: Literal["first", "late"] = "first",
) -> Polarity:
    """Classify whether the target syntax matches the dispense direction
    implied by the target physicals.

    Args:
        force_phys: Mapping of ig_idx -> physical register number.
        target_position: Which end of simplify order the target syntax
            anchors to. "first" (default) corresponds to --want-first
            (target ig_idx values at the START of simplify order).
            "late" corresponds to --want-late (target ig_idx values at
            the END of simplify order). Phase 1 shipped target_position
            handling for "first" only; Phase 3 added "late" support.

    Returns:
        SAFE if force_phys is empty, or if every target physical matches
        the dispense direction for the chosen target_position.
        UNCERTAIN if any target physical is mid-volatile (r4-r9) and no
        physicals are in a definitely-wrong set.
        WRONG_POLARITY if any target physical is in a set that
        structurally cannot match the chosen target_position.

    For target_position="first":
        WRONG_POLARITY when any physical is in HIGH_VOLATILE_REGS
        (r10-r12) — these can't be assigned to early virtuals via
        lowest-first volatile dispense.

    For target_position="late":
        WRONG_POLARITY when any physical is in TOP_NON_VOLATILE_REGS
        (r28-r31) — these are dispensed FIRST by
        obtain_nonvolatile_register, so target ig_idx at the end won't
        get them. Also WRONG_POLARITY when any physical is r3 — the
        lowest workingMask bit, consumed first by lowest-first
        dispense.
    """
    if not force_phys:
        return Polarity.SAFE

    if target_position == "first":
        polarity = Polarity.SAFE
        for phys in force_phys.values():
            if phys in HIGH_VOLATILE_REGS:
                return Polarity.WRONG_POLARITY
            if phys in UNCERTAIN_VOLATILE_REGS:
                polarity = Polarity.UNCERTAIN
        return polarity

    if target_position == "late":
        polarity = Polarity.SAFE
        for phys in force_phys.values():
            if phys in TOP_NON_VOLATILE_REGS or phys == 3:
                return Polarity.WRONG_POLARITY
            if phys in UNCERTAIN_VOLATILE_REGS:
                polarity = Polarity.UNCERTAIN
        return polarity

    raise ValueError(
        f"target_position must be 'first' or 'late', got {target_position!r}"
    )


def find_coalesced_targets(
    events,
    *,
    targets: set[int],
    class_id: int,
) -> set[int]:
    """Return the subset of `targets` that are coalesced as aliases in
    the function's natural coalesce mappings for the given register class.

    "Coalesced as alias" means the target ig_idx appears as the LHS
    (virt) in a `virt -> root` mapping — i.e., MWCC merged it into
    another virtual's allocator node. A target appearing only as the
    RHS (root) of a mapping is still an independent allocator node and
    is NOT considered coalesced.

    Args:
        events: FunctionEvents for the function (from parse_hook_events
            + find_function).
        targets: Set of ig_idx values to check (typically the keys of
            a force_phys mapping).
        class_id: Register class to inspect (0 = GPR, 1 = FPR).

    Returns:
        The subset of `targets` that appears as a coalesce alias LHS.
        Empty if no targets are coalesced, or if `events` is None, or
        if `targets` is empty.
    """
    if events is None or not targets:
        return set()

    coalesced: set[int] = set()
    for section in events.coalesce_sections:
        if section.class_id != class_id:
            continue
        for virt, _root in section.mappings:
            if virt in targets:
                coalesced.add(virt)
    return coalesced


# Lex-encoding multiplier. Each missed prefix slot is worth LEX_BIG points;
# distance.total is added directly. As long as LEX_BIG strictly exceeds any
# plausible distance.total, prefix-level dominates distance.
#
# Sizing rationale: distance.total is bounded by the sum of |IG|, |coalesce|,
# and |spill_set|. For real-world Melee functions these run in the low hundreds;
# even synthetic stress cases haven't crossed 5_000 in the harvest pool we've
# seen. 1_000_000 leaves three orders of magnitude of headroom and is small
# enough that scores fit in Python ints without any boundary worries (permuter
# uses signed 64-bit-ish ints internally, see `Scorer.PENALTY_INF = 10**9`).
LEX_BIG = 1_000_000

# Sentinel score for candidates rejected by the coalesce-preservation
# constraint. Equal to LEX_BIG * 1000, which dominates any normal score
# the function can produce (a normal score is at most
# LEX_BIG * target_len + distance.total, and target_len in practice is
# < 100). Using a constant rather than computing per-call keeps the
# rejection score stable across candidates so permuter can sort them
# consistently.
STRUCTURAL_REJECTION_SCORE: int = LEX_BIG * 1000


@dataclass(frozen=True)
class SimplifyOrderTargetSpec:
    """Configuration for the score-simplify-order command.

    Loaded from a YAML file; the wrapper script + CLI command both
    reference the same spec so the campaign's "what counts as a win" is
    captured in one editable file per function.

    Fields:
      function: Function name to score. Must match the function the
        candidate pcdump was generated for; the scorer validates this.
      simplify_order_target: ig_idx sequence we want at the head of class
        `class_id`'s simplify order. Lower-position = higher priority.
      class_id: Which register class to score against. Defaults to 0
        (GPR). Functions whose target slot is FPR would pass 1.
      baseline_dump: Absolute path to a pcdump for the baseline (known-
        good or pre-search) compile of the function. Used to compute
        `PrecolorDistance` against each candidate.
      force_phys: Optional mapping of ig_idx -> physical register number
        capturing the force-phys assignments the simplify_order_target
        was derived from. When present, enables the pre-flight polarity
        check (see classify_polarity). Defaults to an empty dict for
        backward compatibility with specs predating the polarity check.
      coalesce_preservation: When True (default) and `force_phys` is
        non-empty, candidates that coalesce any `force_phys` key
        ig_idx into another root are rejected by the scorer. When
        False, the constraint is disabled. Has no effect when
        `force_phys` is empty (the check has nothing to look at).
        Deferred-debt #19 Phase 2 build (2026-05-26).
      simplify_order_target_late: ig_idx sequence we want at the END of
        class `class_id`'s simplify order (the suffix). Mutually
        exclusive with `simplify_order_target` — the loader rejects
        specs that set both. Used when target physicals are
        high-volatile (r10-r12), in which case the target ig_idx values
        need to be processed LAST so MWCC's volatile dispense (lowest
        free bit first from workingMask) gives them the high registers.
        Deferred-debt #20 Phase 3 (2026-05-27).
    """

    function: str
    simplify_order_target: tuple[int, ...]
    class_id: int
    baseline_dump: Path
    force_phys: Mapping[int, int] = field(default_factory=dict)
    coalesce_preservation: bool = True
    simplify_order_target_late: tuple[int, ...] = ()


class SimplifyOrderSpecError(ValueError):
    """Raised when a spec file is malformed or references missing inputs."""


def load_simplify_order_target_spec(path: Path) -> SimplifyOrderTargetSpec:
    """Load + validate a YAML target spec.

    Required fields: `function` (str), exactly one of
    `simplify_order_target` or `simplify_order_target_late` (list of int),
    `baseline_dump` (str path). Optional: `class_id` (int, default 0).
    Unknown fields are ignored — forward-compatible with future additions
    (e.g. an `alpha` field for combined-mode scoring, currently documented
    as ignored).

    Raises `SimplifyOrderSpecError` with a clear message for any
    malformed input. The CLI layer catches and prints these.
    """
    if not path.exists():
        raise SimplifyOrderSpecError(
            f"target spec file not found: {path}"
        )
    text = path.read_text(encoding="utf-8")

    # YAML is required for these specs — they're authored by humans and
    # YAML is the canonical form. JSON is implicitly supported because
    # PyYAML's safe_load accepts JSON, but we don't advertise it.
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise SimplifyOrderSpecError(
            f"PyYAML is required to load {path.name}: pip install PyYAML"
        ) from e

    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise SimplifyOrderSpecError(f"failed to parse {path}: {e}") from e

    if not isinstance(data, dict):
        raise SimplifyOrderSpecError(
            f"target spec {path} must be a mapping at top level, "
            f"got {type(data).__name__}"
        )

    function = data.get("function")
    if not isinstance(function, str) or not function:
        raise SimplifyOrderSpecError(
            f"target spec {path}: missing or empty 'function' string"
        )

    raw_target = data.get("simplify_order_target")
    raw_target_late = data.get("simplify_order_target_late")

    if raw_target is not None and raw_target_late is not None:
        raise SimplifyOrderSpecError(
            f"target spec {path}: 'simplify_order_target' and "
            f"'simplify_order_target_late' are mutually exclusive — "
            f"specify exactly one"
        )

    if raw_target is None and raw_target_late is None:
        raise SimplifyOrderSpecError(
            f"target spec {path}: missing 'simplify_order_target' or "
            f"'simplify_order_target_late' list"
        )

    target: list[int] = []
    target_late: list[int] = []

    if raw_target is not None:
        if not isinstance(raw_target, (list, tuple)):
            raise SimplifyOrderSpecError(
                f"target spec {path}: 'simplify_order_target' must be a list of "
                f"integers, got {type(raw_target).__name__}"
            )
        for i, v in enumerate(raw_target):
            if not isinstance(v, int) or isinstance(v, bool):
                raise SimplifyOrderSpecError(
                    f"target spec {path}: 'simplify_order_target[{i}]' = "
                    f"{v!r} is not an integer"
                )
            target.append(v)

    if raw_target_late is not None:
        if not isinstance(raw_target_late, (list, tuple)):
            raise SimplifyOrderSpecError(
                f"target spec {path}: 'simplify_order_target_late' must be "
                f"a list of integers, got {type(raw_target_late).__name__}"
            )
        for i, v in enumerate(raw_target_late):
            if not isinstance(v, int) or isinstance(v, bool):
                raise SimplifyOrderSpecError(
                    f"target spec {path}: "
                    f"'simplify_order_target_late[{i}]' = "
                    f"{v!r} is not an integer"
                )
            target_late.append(v)

    class_id = data.get("class_id", 0)
    if not isinstance(class_id, int) or isinstance(class_id, bool):
        raise SimplifyOrderSpecError(
            f"target spec {path}: 'class_id' must be an integer, got "
            f"{type(class_id).__name__}"
        )

    raw_baseline = data.get("baseline_dump")
    if not isinstance(raw_baseline, str) or not raw_baseline:
        raise SimplifyOrderSpecError(
            f"target spec {path}: missing or empty 'baseline_dump' path"
        )
    baseline_dump = Path(raw_baseline).expanduser()
    if not baseline_dump.is_absolute():
        # Resolve relative paths against the spec file's directory so
        # specs can be moved alongside the dump without breaking.
        baseline_dump = (path.parent / baseline_dump).resolve()
    if not baseline_dump.exists():
        raise SimplifyOrderSpecError(
            f"target spec {path}: baseline_dump {baseline_dump} does not exist"
        )

    # Optional force_phys mapping (deferred debt #20: pre-flight polarity check).
    raw_force_phys = data.get("force_phys", {})
    if raw_force_phys is None:
        raw_force_phys = {}
    if not isinstance(raw_force_phys, dict):
        raise SimplifyOrderSpecError(
            f"target spec {path}: 'force_phys' must be a mapping of "
            f"ig_idx (int) -> phys_reg (int), got "
            f"{type(raw_force_phys).__name__}"
        )
    force_phys: dict[int, int] = {}
    for k, v in raw_force_phys.items():
        if not isinstance(k, int) or isinstance(k, bool):
            raise SimplifyOrderSpecError(
                f"target spec {path}: 'force_phys' requires integer key, "
                f"got {k!r} ({type(k).__name__})"
            )
        if not isinstance(v, int) or isinstance(v, bool):
            raise SimplifyOrderSpecError(
                f"target spec {path}: 'force_phys[{k}]' requires integer value "
                f"(bare register number, not 'r31'), got {v!r} "
                f"({type(v).__name__})"
            )
        force_phys[k] = v

    # Optional coalesce_preservation flag (deferred debt #19).
    raw_coalesce = data.get("coalesce_preservation", True)
    if not isinstance(raw_coalesce, bool):
        raise SimplifyOrderSpecError(
            f"target spec {path}: 'coalesce_preservation' must be a bool "
            f"(true/false), got {type(raw_coalesce).__name__}"
        )

    return SimplifyOrderTargetSpec(
        function=function,
        simplify_order_target=tuple(target),
        class_id=class_id,
        baseline_dump=baseline_dump,
        force_phys=force_phys,
        coalesce_preservation=raw_coalesce,
        simplify_order_target_late=tuple(target_late),
    )


@dataclass(frozen=True)
class SimplifyOrderScoreResult:
    """Output of `compute_lex_score`. Carries the integer + components.

    The score itself is the permuter-facing integer; the components are
    retained so the `--breakdown` / `--json` CLI output can render the
    breakdown without recomputing.

    Fields added in Phase 2 Task 3 (coalesce-preservation constraint):
      structural_rejection: True if the candidate was rejected because one
        or more force_phys key ig_idx values are coalesced in the candidate's
        natural coalesce mappings. When True, `score` equals
        STRUCTURAL_REJECTION_SCORE. False for all normally-scored candidates.
      coalesced_targets: The subset of force_phys keys that were found as
        coalesced aliases in the candidate's pcdump. Non-empty only when
        structural_rejection is True.

    Field added in Phase 3 Task 3 (late-target suffix scoring):
      common_suffix_length: Number of positions from the END of the
        candidate's filtered simplify order that match the corresponding
        suffix of `simplify_order_target_late`. Non-zero only in late-mode
        (when `spec.simplify_order_target_late` is non-empty). Defaults to
        0 for all front-mode candidates and for structurally-rejected
        candidates.
    """

    score: int
    simplify_score: SimplifyScore
    precolor_distance: PrecolorDistance
    structural_rejection: bool = False
    coalesced_targets: frozenset[int] = frozenset()
    common_suffix_length: int = 0


def _filter_meaningful_order(order: tuple[int, ...]) -> tuple[int, ...]:
    """Drop placeholder (-1) entries from a simplify order.

    The colorgraph parser yields a `SimplifyEntry` for every row emitted
    by the `simplifygraph` hook, and `ig_idx == -1` is the parser's
    encoding for "physical-reg / pre-allocated / non-virtual-register"
    decisions — rows that aren't part of the virtual-register interference
    graph at all (see `colorgraph_parser.SimplifyEntry`). For the lex
    scorer the user cares about the *abstract* relative order of real
    `ig_idx` nodes ("X before Y"), not the literal row position, and the
    `-1` placeholders are noise that varies across compilations and would
    otherwise drown out that signal.

    Concrete example surfaced by the ftColl_8007BAC0 campaign (2026-05-24):
    the raw simplify order was ``[-1, -1, ..., 41 (pos 9), ..., 37 (pos 13), ...]``,
    so a `--want-first 37,41` target — meaning "37 and 41 should be the
    first two meaningful nodes" — could never match the literal prefix
    ``(-1, -1)``. After filtering, the same order becomes
    ``(..., 41, ..., 37, ...)`` and the scorer can express the goal as a
    prefix comparison again.
    """
    return tuple(x for x in order if x != -1)


def common_suffix_length(
    observed: tuple[int, ...],
    target: tuple[int, ...],
) -> int:
    """Return the length of the longest suffix of `observed` that matches
    the corresponding suffix of `target`.

    Mirror of the existing prefix-match logic but anchored from the end.
    Used by `compute_lex_score` when `spec.simplify_order_target_late` is
    set (i.e., target nodes should appear at the END of simplify order).

    Args:
        observed: The candidate's filtered simplify-order positions.
        target: The desired sequence at the end of simplify order.

    Returns:
        Integer count of matching positions from the end. Zero if either
        sequence is empty, or if they don't match at the last position.
    """
    if not observed or not target:
        return 0
    n = min(len(observed), len(target))
    matched = 0
    for i in range(1, n + 1):
        if observed[-i] == target[-i]:
            matched += 1
        else:
            break
    return matched


def compute_lex_score(
    baseline: BaselineSignature,
    candidate: BaselineSignature,
    target: tuple[int, ...],
    *,
    candidate_events: Optional[FunctionEvents] = None,
    spec: Optional[SimplifyOrderTargetSpec] = None,
) -> SimplifyOrderScoreResult:
    """Compute the lex-encoded score for one candidate against baseline.

    See module docstring for the formula. Both baseline and candidate
    must be from the same register class (caller's responsibility).

    The `target` is defensively filtered for `-1` entries before scoring
    so a spec authoring mistake (placeholders in `simplify_order_target`)
    silently does the right thing rather than producing scores that can
    never reach 0. The signatures themselves are *expected* to be already
    filtered by `extract_signature`, but pass through `_filter_meaningful_order`
    here too for the same reason — defense in depth.

    For an empty target: missed prefix is 0 (you can't miss what isn't
    targeted), so score collapses to just `distance.total`. This is
    deliberate — it lets a campaign use this scorer to minimize precolor
    distance alone, without specifying any simplify-order goal. Document
    this as a feature rather than treating empty-target as an error.

    Optional keyword args for the coalesce-preservation constraint
    (Phase 2 Task 3, deferred debt #19):
      candidate_events: FunctionEvents for the candidate (from
        parse_hook_events + find_function). Required for the constraint
        to run; ignored if None.
      spec: The SimplifyOrderTargetSpec that controls the constraint via
        spec.coalesce_preservation and spec.force_phys. When both
        candidate_events and spec are supplied AND
        spec.coalesce_preservation is True AND spec.force_phys is
        non-empty, the function checks whether any force_phys key ig_idx
        appears as a coalesce alias in the candidate's natural coalesce
        mappings for spec.class_id. If any do, STRUCTURAL_REJECTION_SCORE
        is returned immediately, before prefix/distance computation.

    Callers that don't pass candidate_events or spec get identical
    behavior to the old three-argument form (fully backward-compatible).
    """
    # Coalesce-preservation constraint (deferred debt #19).
    coalesced: frozenset[int] = frozenset()
    if (
        candidate_events is not None
        and spec is not None
        and spec.coalesce_preservation
        and spec.force_phys
    ):
        coalesced_set = find_coalesced_targets(
            candidate_events,
            targets=set(spec.force_phys.keys()),
            class_id=spec.class_id,
        )
        if coalesced_set:
            coalesced = frozenset(coalesced_set)
            # Build placeholder simplify/distance objects so the result
            # dataclass is fully populated even on the rejection path.
            # The values are zero/empty — callers should check
            # structural_rejection before reading these fields.
            _empty_dist = precolor_distance(
                _signature_with_filtered_order(baseline),
                _signature_with_filtered_order(baseline),
            )
            _filtered_target = _filter_meaningful_order(target)
            _baseline_filt = _signature_with_filtered_order(baseline)
            _placeholder_simp = score_simplify_order(
                _baseline_filt, _baseline_filt, _filtered_target
            )
            return SimplifyOrderScoreResult(
                score=STRUCTURAL_REJECTION_SCORE,
                simplify_score=_placeholder_simp,
                precolor_distance=_empty_dist,
                structural_rejection=True,
                coalesced_targets=coalesced,
                common_suffix_length=0,
            )

    filtered_target = _filter_meaningful_order(target)
    baseline = _signature_with_filtered_order(baseline)
    candidate = _signature_with_filtered_order(candidate)
    dist = precolor_distance(baseline, candidate)

    # Phase 3: late-mode branch (suffix scoring).
    # When spec has a simplify_order_target_late, switch from prefix-matching
    # to suffix-matching. The coalesce-preservation constraint above already
    # ran (early-return path), so we only reach here for non-rejected candidates.
    target_late = spec.simplify_order_target_late if spec is not None else ()
    if target_late:
        filtered_target_late = _filter_meaningful_order(target_late)
        observed_order = candidate.simplify_order
        suffix_len = common_suffix_length(observed_order, filtered_target_late)
        late_target_len = len(filtered_target_late)
        missed_late = late_target_len - suffix_len
        score = missed_late * LEX_BIG + dist.total
        # Build a placeholder SimplifyScore using the empty filtered_target so
        # the result dataclass is fully populated. Callers should read
        # common_suffix_length for the meaningful metric in late-mode.
        _placeholder_simp = score_simplify_order(baseline, baseline, filtered_target)
        return SimplifyOrderScoreResult(
            score=score,
            simplify_score=_placeholder_simp,
            precolor_distance=dist,
            structural_rejection=False,
            coalesced_targets=frozenset(),
            common_suffix_length=suffix_len,
        )

    # Existing front-mode (prefix-match) path — unchanged.
    simp = score_simplify_order(baseline, candidate, filtered_target)
    target_len = len(filtered_target)
    missed = target_len - simp.common_prefix_length
    score = missed * LEX_BIG + dist.total
    return SimplifyOrderScoreResult(
        score=score,
        simplify_score=simp,
        precolor_distance=dist,
        structural_rejection=False,
        coalesced_targets=frozenset(),
        common_suffix_length=0,
    )


def _signature_with_filtered_order(sig: BaselineSignature) -> BaselineSignature:
    """Return `sig` with placeholder ig_idx entries dropped from `simplify_order`.

    Cheap no-op (returns the same object) when the order has no `-1`s, so
    safe to call defensively on already-filtered signatures.
    """
    filtered = _filter_meaningful_order(sig.simplify_order)
    if filtered == sig.simplify_order:
        return sig
    return BaselineSignature(
        interference_edges=sig.interference_edges,
        coalesce_mappings=sig.coalesce_mappings,
        spill_set=sig.spill_set,
        simplify_order=filtered,
    )


def extract_signature(
    pcdump_text: str,
    function: str,
    *,
    class_id: int,
) -> Optional[BaselineSignature]:
    """Parse a pcdump and pull the BaselineSignature for `function`.

    Returns None if the function isn't in the dump. The CLI layer treats
    this as "candidate didn't produce events for this function" — likely
    a compile or codegen path failure — and emits a sentinel high score
    so permuter discards it.

    The returned signature's `simplify_order` is filtered to drop `-1`
    placeholder entries (see `_filter_meaningful_order`). The abstract
    target the scorer evaluates is "real node X appears before real node
    Y," not "node X sits at literal row N" — `-1` rows are placeholders
    for non-virtual-register decisions (pre-allocated nodes, physical
    regs, linear-scan failures) that vary across compilations and would
    otherwise drown out the real signal. Surfaced by the ftColl_8007BAC0
    campaign on 2026-05-24, where the raw simplify order
    ``[-1, -1, ..., 41 (pos 9), ..., 37 (pos 13), ...]`` made it
    impossible to express "37 should come before 41" as a prefix.

    Filtering is applied here (Option A) rather than at compare time
    (Option B) so that every downstream consumer of the signature sees a
    consistent shape. The raw simplify order is still available via
    `simplify_search.baseline_signature` for callers that genuinely need
    the row-level view (e.g. `mutate_simplify_order_cmd`, which mutates
    by position).
    """
    events_list = parse_hook_events(pcdump_text)
    events = find_function(events_list, function)
    if events is None:
        return None
    return _signature_with_filtered_order(
        baseline_signature(events, class_id=class_id)
    )
