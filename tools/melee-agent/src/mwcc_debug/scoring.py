"""Score a pcdump's coloring decisions against a target spec.

Tier 4 v1 — exposes a single floating-point score combining:
- byte distance (% of virtuals at the wrong physical)
- spill penalty (unexpected SPILLED markers)
- interferer distance (degree differences vs target)

Lower scores are better; a perfect match has score 0. Compatible with
the upstream decomp-permuter convention.

The target spec is a dict (loaded from YAML or constructed in code) of
the shape:

    {
        "function": "mnVibration_80248644",
        "virtuals": {
            32: 26,   # r32 -> r26
            35: 29,
            36: 31,   # critical mapping
            # ...
        },
        # Optional:
        "spilled": [],  # virtual indices expected to carry SPILLED flag
    }

Missing virtuals in `virtuals` are ignored (treated as "don't care").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .colorgraph_parser import FunctionEvents, SimplifySection
from .frame_reservations import analyze_frame_from_function
from .parser import Function, VirtualRegInfo, analyze_function


# Score weights — see docs/mwcc-debug-tier4-permuter.md for derivation.
# Adjust by passing a custom ScoreWeights instance.
@dataclass
class ScoreWeights:
    byte: float = 100.0
    virtual: float = 10.0
    spill: float = 5.0
    interferer: float = 1.0
    frame_size: float = 1.0
    frame_unused: float = 0.25


_DEFAULT_WEIGHTS = ScoreWeights()


@dataclass
class ScoreBreakdown:
    """Decomposition of a score, for diagnosis."""

    total: float
    virtual_distance: int  # count of virtuals with wrong physical
    virtual_penalty: float  # weighted contribution
    spill_unexpected: list[int]  # virtual indices that got SPILLED unexpectedly
    spill_missing: list[int]  # virtuals expected to spill but didn't
    spill_penalty: float
    interferer_distance: int  # sum of |target_degree - actual_degree|
    interferer_penalty: float
    # Per-virtual diff list for the guide command
    wrong: list[tuple[int, int, int]]  # (virtual, target_phys, actual_phys)
    matched: int  # count of correctly-mapped virtuals
    targeted: int  # count of virtuals named in target
    frame_targeted: bool
    frame_size_actual: int | None
    frame_size_target: int | None
    frame_size_distance: int
    frame_unused_distance: int
    frame_penalty: float


def _range_signature(ranges: list[dict]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for item in ranges:
        try:
            out.add((int(item["start"]), int(item["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _range_symmetric_distance(actual: list[dict], target: list[dict]) -> int:
    actual_ranges = _range_signature(actual)
    target_ranges = _range_signature(target)
    distance = 0
    for start, end in actual_ranges.symmetric_difference(target_ranges):
        distance += max(0, end - start)
    return distance


def _coerce_frame_target(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    return raw


def _virtuals_from_analyze(fn: Function) -> dict[int, VirtualRegInfo]:
    """Run analyze_function and return a dict keyed by virtual number."""
    return {v.virtual: v for v in analyze_function(fn)}


def _spilled_from_events(events: Optional[FunctionEvents]) -> set[int]:
    """Collect `ig_idx` of all SPILLED-flagged nodes across all simplify
    sections of `events`. `ig_idx` corresponds to the IG node index;
    for virtual regs this equals the virtual number when MWCC builds
    the IG via `interferencegraph[]` 1:1 indexing (typical case).
    """
    spilled: set[int] = set()
    if events is None:
        return spilled
    for sec in events.simplify_sections:
        for entry in sec.entries:
            if entry.spilled and entry.ig_idx >= 0:
                spilled.add(entry.ig_idx)
    return spilled


def score_function(
    fn: Function,
    target: dict,
    events: Optional[FunctionEvents] = None,
    weights: ScoreWeights = _DEFAULT_WEIGHTS,
) -> ScoreBreakdown:
    """Score `fn`'s coloring decisions against `target`.

    `fn` should be a parsed Function from parse_pcdump.
    `events` (optional) supplies SIMPLIFY GRAPH spill data.
    `target` follows the format documented at the module top.
    """
    target_virtuals = target.get("virtuals", {})
    # Coerce keys to int (YAML may load them as str)
    target_virtuals = {int(k): int(v) for k, v in target_virtuals.items()}
    target_spilled = set(int(v) for v in target.get("spilled", []))

    actual = _virtuals_from_analyze(fn)

    wrong: list[tuple[int, int, int]] = []
    matched = 0
    for v, tgt_phys in target_virtuals.items():
        info = actual.get(v)
        actual_phys = info.physical if info else None
        if actual_phys == tgt_phys:
            matched += 1
        else:
            wrong.append((v, tgt_phys, actual_phys if actual_phys is not None else -1))

    actual_spilled = _spilled_from_events(events)
    # Unexpected: spilled in actual but not in target
    spill_unexpected = sorted(actual_spilled - target_spilled)
    # Missing: spilled in target but not in actual
    spill_missing = sorted(target_spilled - actual_spilled)

    # Interferer distance — sum of |actual_array_size - target_n_interferers|.
    # We only have target degree if user supplied it; otherwise this term is 0.
    target_degrees = target.get("degrees", {})
    target_degrees = {int(k): int(v) for k, v in target_degrees.items()}
    interferer_distance = 0
    for v, tgt_deg in target_degrees.items():
        info = actual.get(v)
        actual_deg = len(info.interferes_with) if info else 0
        interferer_distance += abs(tgt_deg - actual_deg)

    virtual_distance = len(wrong)
    virtual_penalty = virtual_distance * weights.virtual
    spill_penalty = (len(spill_unexpected) + len(spill_missing)) * weights.spill
    interferer_penalty = interferer_distance * weights.interferer

    target_frame = _coerce_frame_target(target.get("frame"))
    frame_targeted = bool(target_frame)
    frame_size_actual = None
    frame_size_target = None
    frame_size_distance = 0
    frame_unused_distance = 0
    if frame_targeted:
        actual_frame = analyze_frame_from_function(fn)
        frame_size_actual = actual_frame.get("frame_size")
        raw_target_frame_size = target_frame.get("frame_size")
        if raw_target_frame_size is not None:
            try:
                frame_size_target = int(raw_target_frame_size)
            except (TypeError, ValueError):
                frame_size_target = None
        if frame_size_actual is not None and frame_size_target is not None:
            frame_size_distance = abs(frame_size_actual - frame_size_target)
        target_unused_ranges = target_frame.get("unused_ranges")
        if isinstance(target_unused_ranges, list):
            frame_unused_distance = _range_symmetric_distance(
                actual_frame.get("unused_ranges", []),
                target_unused_ranges,
            )
    frame_penalty = (
        frame_size_distance * weights.frame_size
        + frame_unused_distance * weights.frame_unused
    )

    # Byte distance is not directly computable from pcdump alone (we'd need
    # the target .o for that). For now it's a synthetic stand-in:
    # 100 * (1 - matched/targeted) — i.e. fraction of target NOT met,
    # scaled to %.
    targeted = len(target_virtuals)
    if targeted > 0:
        byte_pct_miss = (targeted - matched) / targeted * 100.0
    else:
        byte_pct_miss = 0.0
    byte_penalty = byte_pct_miss * weights.byte / 100.0

    total = (
        byte_penalty
        + virtual_penalty
        + spill_penalty
        + interferer_penalty
        + frame_penalty
    )

    return ScoreBreakdown(
        total=total,
        virtual_distance=virtual_distance,
        virtual_penalty=virtual_penalty,
        spill_unexpected=spill_unexpected,
        spill_missing=spill_missing,
        spill_penalty=spill_penalty,
        interferer_distance=interferer_distance,
        interferer_penalty=interferer_penalty,
        wrong=wrong,
        matched=matched,
        targeted=targeted,
        frame_targeted=frame_targeted,
        frame_size_actual=frame_size_actual,
        frame_size_target=frame_size_target,
        frame_size_distance=frame_size_distance,
        frame_unused_distance=frame_unused_distance,
        frame_penalty=frame_penalty,
    )


def derive_target_from_function(fn: Function,
                                events: Optional[FunctionEvents] = None) -> dict:
    """Build a target spec from the current state of `fn`. Useful for
    capturing experimental (e.g. force-phys-aided) targets.
    """
    infos = analyze_function(fn)
    virtuals: dict[int, int] = {}
    for info in infos:
        if info.physical is not None:
            virtuals[info.virtual] = info.physical

    spilled: list[int] = []
    if events is not None:
        for sec in events.simplify_sections:
            for entry in sec.entries:
                if entry.spilled and entry.ig_idx >= 0:
                    spilled.append(entry.ig_idx)
    spilled = sorted(set(spilled))

    spec = {
        "function": fn.name,
        "virtuals": virtuals,
        "spilled": spilled,
    }
    frame = analyze_frame_from_function(fn)
    if frame.get("frame_size") is not None:
        spec["frame"] = {
            "frame_size": frame["frame_size"],
            "access_ranges": frame.get("access_ranges", []),
            "unused_ranges": frame.get("unused_ranges", []),
            "symbolic_home_map": frame.get("symbolic_home_map", []),
        }
    return spec
