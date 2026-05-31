"""Targeted source-variant search guided by the register allocator's simplify order.

The `grVenom_80204284` campaign found that for some stuck functions, the
remaining RA-input mismatch is *only* in the simplify order's head — the
interference graph, coalesce mappings, and spill set are already shaped
correctly. `mwcc-debug` can prove the result with `--force-iter-first` but
existing source-mutation primitives don't naturally produce it.

This module is the search driver that:

1. Pulls baseline `(IG, coalesce, simplify_order, spills)` from a known-good
   pcdump.
2. Iterates source variants from one or more `VariantSource`s.
3. For each variant, compiles via the existing `diff_capture` machinery,
   extracts its signature, applies the preserve-precolor gate, and scores
   simplify-order proximity.
4. Returns ranked surviving candidates plus aggregate statistics.

The variant-stream architecture (a `VariantSource` is just an iterator of
`SourceVariant`s) keeps the driver agnostic to where candidates come from.
Existing-primitive adapters ship in `simplify_variants.py`; permuter
integration would slot in as another adapter.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .colorgraph_parser import FunctionEvents, parse_hook_events
from .colorgraph_parser import find_function as find_event_function
from .diff_capture import CompileFailure, DiffInput, compile_source_variant


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineSignature:
    """The four RA-input components for one register class.

    Three of these (`interference_edges`, `coalesce_mappings`, `spill_set`)
    are what we want to *preserve* across variants — they describe the
    pre-coloring shape. The fourth (`simplify_order`) is what we want to
    *change*: the search reads its first K entries against a target prefix.
    """

    interference_edges: frozenset[tuple[int, int]]
    coalesce_mappings: frozenset[tuple[int, int]]
    spill_set: frozenset[int]
    simplify_order: tuple[int, ...]


@dataclass(frozen=True)
class GateResult:
    """Outcome of the preserve-precolor gate.

    `passed=True` if all three preserve components match; `reason` is
    a one-line description of the first mismatching component when
    `passed=False`.
    """

    passed: bool
    reason: str


@dataclass(frozen=True)
class SimplifyScore:
    """How well a candidate's simplify_order matches the target prefix."""

    target_prefix: tuple[int, ...]
    observed_prefix: tuple[int, ...]
    common_prefix_length: int
    is_exact_match: bool
    baseline_common_prefix_length: int


@dataclass(frozen=True)
class PrecolorDistance:
    """Per-component symmetric set differences for the three preserve components.

    Counts how many interference-graph edges, coalesce mappings, and spill-set
    entries a candidate added or removed relative to baseline. The binary
    `preserve_precolor` gate collapses all of these to a single bool; this
    type keeps the numeric distance so the search driver can rank candidates
    by combined progress-vs-disturbance score (campaign 3 found 19 permuter
    candidates that hit the target simplify order but every one of them also
    disturbed precolor — the binary gate threw them all out with no further
    signal).

    `total` is the sum across all six counts: it's the obvious single-integer
    "how far off precolor is this candidate" metric. Each component is also
    available individually so the renderer can show the breakdown.
    """

    ig_added: int
    ig_removed: int
    coalesce_added: int
    coalesce_removed: int
    spill_added: int
    spill_removed: int

    @property
    def total(self) -> int:
        return (
            self.ig_added + self.ig_removed
            + self.coalesce_added + self.coalesce_removed
            + self.spill_added + self.spill_removed
        )


# Default alpha for combining simplify-progress with precolor-distance.
# Reasoning: the 5K-candidate grVenom_80204284 batch on 2026-05-23 surfaced
# 120 prefix=2 candidates with distances in the 100-300+ range — much
# larger than the 1..30 estimate originally used to pick alpha=0.05. With
# alpha=0.05 every prefix=2 candidate scored worse than a prefix=0/0
# candidate (1.0 − 0.05×100 = −4.0 versus 0.0), inverting the queue
# users actually want.
#
# alpha=0.001 keeps "prefix=2/2 with distance=500" (combined=0.5) tied
# with "prefix=1/2 with distance=0" (combined=0.5) and above any prefix=0
# candidate, while still preferring smaller disturbance within a prefix
# level. This is a stopgap calibration matched to observed permuter
# distances; the lexicographic rank-mode (sorted by prefix length first,
# then distance) is the calibration-free successor and is being built.
# Exposed as `--combined-alpha` for further tuning per campaign.
DEFAULT_COMBINED_ALPHA = 0.001


@dataclass(frozen=True)
class CombinedScore:
    """Combined simplify-order progress and precolor-disturbance score.

    `combined = simplify_progress_ratio - alpha * precolor_distance.total`.
    Higher is better. The progress ratio is the candidate's
    `common_prefix_length / len(target)`, so it's in [0, 1] when target is
    non-empty; for empty target we define the ratio as 0.0 (since there's
    no progress to measure) and the combined score collapses to
    `-alpha * distance`.
    """

    simplify_score: SimplifyScore
    precolor_distance: PrecolorDistance
    combined: float


@dataclass(frozen=True)
class FunctionContext:
    """The function under search.

    `unit` is the report.json-style unit name (e.g. "melee/mn/mnvibration"),
    `source_path` is the .c file that variants are based on.
    """

    function: str
    unit: str
    source_path: Path
    melee_root: Path


@dataclass(frozen=True)
class SourceVariant:
    """One source variant. `text` is the full .c file content."""

    text: str
    provenance: str
    parent_baseline: Path


@dataclass(frozen=True)
class ScoredVariant:
    """A variant that survived the gate, with its score attached.

    `precolor_distance` is included even for gate-passing candidates — when
    the gate is on, the distance will be all zeros (since the gate passed
    by construction). When the gate is off (`--no-preserve-precolor`),
    gate-passing candidates may have nonzero distance; explicit is better
    than implicit, and the rank-combined ranking treats both buckets
    uniformly.
    """

    variant: SourceVariant
    signature: BaselineSignature
    score: SimplifyScore
    precolor_distance: PrecolorDistance


@dataclass(frozen=True)
class RejectedCandidate:
    """A variant that was gate-rejected but still scored.

    Retains just enough to drive the gate-rejected diagnostic histogram:
    where the variant came from (`provenance`), how its simplify order
    compared to the target (`score`), and why the gate kicked it out
    (`rejection_reason`). The full variant text is intentionally not
    kept — provenance is the traceability handle, and we expect to
    retain hundreds of these per campaign.

    `precolor_distance` records *how much* the candidate disturbed precolor,
    not just *whether* it disturbed it. Two candidates with identical
    simplify-order prefix can still rank differently if one only added one
    edge while the other added ten — the combined score uses this directly.
    """

    provenance: str
    score: SimplifyScore
    rejection_reason: str
    precolor_distance: PrecolorDistance


@dataclass(frozen=True)
class SearchResult:
    """Output of `search()`.

    Fields:
      exact_match: First variant whose signature exactly matches the target
        prefix (and passes the gate). `None` if no such variant was found.
      progress: Variants that passed the gate AND made strictly more
        prefix progress than baseline, ranked by `common_prefix_length` DESC.
        Excludes the exact match (which is already in `exact_match`).
      gate_rejected_count: How many variants were rejected by the gate.
      gate_rejection_reasons: Sample of human-readable rejection reasons
        (deduped; capped to keep CLI output usable).
      rejected_scored: Per-candidate diagnostic record for every gate-rejected
        variant — its provenance, simplify-order score, and rejection reason.
        Populated even when the gate fails so the caller can see whether any
        rejected candidate moved simplify-order toward target (the key
        decision input for harvest-mode vs. custom-scorer tooling).
        Currently uncapped — each entry is ~100 bytes (provenance string +
        SimplifyScore + reason), so even 1000+ rejections is well under 1 MB.
        If memory ever becomes a concern we'd cap and drop the worst-scoring
        overflow.
      compile_failure_count: How many variants failed to compile.
      total_compiles: How many variants were sent through the compile path
        (includes failures and gate-rejected). Bounded by `max_candidates`.
      elapsed_seconds: Wall-clock duration of the search.
    """

    exact_match: SourceVariant | None
    progress: list[ScoredVariant]
    gate_rejected_count: int = 0
    gate_rejection_reasons: list[str] = field(default_factory=list)
    rejected_scored: list[RejectedCandidate] = field(default_factory=list)
    compile_failure_count: int = 0
    total_compiles: int = 0
    elapsed_seconds: float = 0.0


# A variant source is a callable: ctx -> Iterable[SourceVariant]. Use
# Iterable (not Iterator) so adapters can return a precomputed `list` or
# any other iterable without having to wrap it in a generator. The driver
# only does `for variant in source(ctx):`, which works against any
# iterable.
VariantSource = Callable[[FunctionContext], Iterable[SourceVariant]]


# ---------------------------------------------------------------------------
# Baseline signature extraction
# ---------------------------------------------------------------------------


def baseline_signature(events: FunctionEvents, *, class_id: int) -> BaselineSignature:
    """Build a `BaselineSignature` from one `FunctionEvents` and class id.

    Reuses the same shape as `diff_report.py`'s per-component helpers; the
    differences are this returns immutable frozensets/tuples suitable for
    set-of-signatures dedup, and bundles all four components into one
    dataclass.
    """
    edges = _interference_edges(events, class_id)
    mappings = _coalesce_mappings(events, class_id)
    spills = _spill_set(events, class_id)
    order = _simplify_order(events, class_id)
    return BaselineSignature(
        interference_edges=frozenset(edges),
        coalesce_mappings=frozenset(mappings),
        spill_set=frozenset(spills),
        simplify_order=order,
    )


def _interference_edges(events: FunctionEvents, class_id: int) -> set[tuple[int, int]]:
    """Normalized (min, max) edges from the colorgraph section."""
    edges: set[tuple[int, int]] = set()
    for section in events.colorgraph_sections:
        if section.class_id != class_id:
            continue
        for decision in section.decisions:
            if decision.ig_idx < 0:
                continue
            for other_idx, _reg in decision.interferers:
                if other_idx < 0 or other_idx == decision.ig_idx:
                    continue
                lo, hi = sorted((decision.ig_idx, other_idx))
                edges.add((lo, hi))
    return edges


def _coalesce_mappings(events: FunctionEvents, class_id: int) -> set[tuple[int, int]]:
    """(virt, root) pairs from the COALESCE section."""
    out: set[tuple[int, int]] = set()
    for section in events.coalesce_sections:
        if section.class_id == class_id:
            out.update(section.mappings)
    return out


def _spill_set(events: FunctionEvents, class_id: int) -> set[int]:
    """ig_idxs flagged by simplifygraph (flags & 0x08)."""
    out: set[int] = set()
    for section in events.simplify_sections:
        if section.class_id != class_id:
            continue
        for entry in section.entries:
            if entry.spilled and entry.ig_idx >= 0:
                out.add(entry.ig_idx)
    return out


def _simplify_order(events: FunctionEvents, class_id: int) -> tuple[int, ...]:
    """ig_idx order from the simplify section, in iter_idx order."""
    for section in events.simplify_sections:
        if section.class_id == class_id:
            return tuple(e.ig_idx for e in section.entries)
    return ()


# ---------------------------------------------------------------------------
# Preserve-precolor gate
# ---------------------------------------------------------------------------


def preserve_precolor(
    baseline: BaselineSignature, candidate: BaselineSignature,
) -> GateResult:
    """Reject variants that disturb the pre-coloring shape.

    The gate passes if and only if `interference_edges`, `coalesce_mappings`,
    and `spill_set` all match between baseline and candidate. The simplify
    order itself is allowed (and expected) to differ — that's what the
    search is trying to manipulate.

    Returns a GateResult with `passed` and (when failing) a `reason` string
    naming the first component that differs.
    """
    if baseline.interference_edges != candidate.interference_edges:
        added = sorted(candidate.interference_edges - baseline.interference_edges)
        removed = sorted(baseline.interference_edges - candidate.interference_edges)
        return GateResult(
            passed=False,
            reason=(
                f"interference graph differs "
                f"(added={added[:3]}, removed={removed[:3]})"
            ),
        )
    if baseline.coalesce_mappings != candidate.coalesce_mappings:
        added = sorted(candidate.coalesce_mappings - baseline.coalesce_mappings)
        removed = sorted(baseline.coalesce_mappings - candidate.coalesce_mappings)
        return GateResult(
            passed=False,
            reason=(
                f"coalesce mappings differ "
                f"(added={added[:3]}, removed={removed[:3]})"
            ),
        )
    if baseline.spill_set != candidate.spill_set:
        added = sorted(candidate.spill_set - baseline.spill_set)
        removed = sorted(baseline.spill_set - candidate.spill_set)
        return GateResult(
            passed=False,
            reason=(
                f"spill set differs "
                f"(added={added[:3]}, removed={removed[:3]})"
            ),
        )
    return GateResult(passed=True, reason="")


def precolor_distance(
    baseline: BaselineSignature, candidate: BaselineSignature,
) -> PrecolorDistance:
    """Per-component symmetric set differences between baseline and candidate.

    Unlike `preserve_precolor` (which collapses to a single bool), this
    returns the numeric distance for each of the three preserve components.
    Counts what the candidate *added* relative to baseline (elements present
    in candidate but not baseline) and what it *removed* (vice versa) for
    each of IG edges, coalesce mappings, and spill set.

    Symmetric-difference rather than just "size of symmetric difference"
    because the add/remove asymmetry can hint at the *direction* of the
    disturbance — e.g. permuter often adds spurious interferences without
    removing real ones, and that's a different kind of disturbance than
    coalesce mappings being remapped through different roots.
    """
    return PrecolorDistance(
        ig_added=len(candidate.interference_edges - baseline.interference_edges),
        ig_removed=len(baseline.interference_edges - candidate.interference_edges),
        coalesce_added=len(candidate.coalesce_mappings - baseline.coalesce_mappings),
        coalesce_removed=len(baseline.coalesce_mappings - candidate.coalesce_mappings),
        spill_added=len(candidate.spill_set - baseline.spill_set),
        spill_removed=len(baseline.spill_set - candidate.spill_set),
    )


# ---------------------------------------------------------------------------
# Simplify-order scoring
# ---------------------------------------------------------------------------


def score_simplify_order(
    baseline: BaselineSignature,
    candidate: BaselineSignature,
    target: tuple[int, ...],
) -> SimplifyScore:
    """Score how well a candidate's simplify order matches the target prefix.

    The target is a sequence of ig_idxs we want at the *head* of the
    simplify order. A win is when the candidate's order starts with
    exactly `target` (`is_exact_match=True`). Otherwise we report
    `common_prefix_length` (how many positions of target are matched at the
    start) so the caller can compare against the baseline's own match length.

    `target=()` is treated as a trivial match — useful for testing.
    """
    observed_prefix = candidate.simplify_order[: len(target)]
    baseline_prefix = baseline.simplify_order[: len(target)]

    common_len = _common_prefix_len(observed_prefix, target)
    baseline_common = _common_prefix_len(baseline_prefix, target)

    return SimplifyScore(
        target_prefix=target,
        observed_prefix=observed_prefix,
        common_prefix_length=common_len,
        is_exact_match=(common_len == len(target)),
        baseline_common_prefix_length=baseline_common,
    )


def _score_simplify_order_suffix(
    baseline: BaselineSignature,
    candidate: BaselineSignature,
    target_late: tuple[int, ...],
) -> SimplifyScore:
    """Score how well a candidate's simplify order matches the target suffix.

    The target is a sequence of ig_idxs we want at the *tail* of the
    simplify order (late-mode, corresponding to ``--want-late``). Reuses
    ``SimplifyScore`` with ``common_prefix_length`` repurposed as the
    suffix-match count so all downstream ranking and progress-detection
    logic works unchanged.

    ``target_late=()`` is treated as a trivial exact match.
    """
    n = len(target_late)
    observed_suffix = tuple(candidate.simplify_order[-n:]) if n else ()
    baseline_suffix = tuple(baseline.simplify_order[-n:]) if n else ()

    suffix_len = _common_suffix_length(observed_suffix, target_late)
    baseline_suffix_len = _common_suffix_length(baseline_suffix, target_late)

    return SimplifyScore(
        target_prefix=target_late,
        observed_prefix=observed_suffix,
        common_prefix_length=suffix_len,
        is_exact_match=(suffix_len == n),
        baseline_common_prefix_length=baseline_suffix_len,
    )


def _common_prefix_len(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x == y:
            n += 1
        else:
            break
    return n


def _common_suffix_length(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Return the number of trailing elements shared by a and b."""
    n = min(len(a), len(b))
    matched = 0
    for i in range(1, n + 1):
        if a[-i] == b[-i]:
            matched += 1
        else:
            break
    return matched


def combined_value(
    simplify_score: SimplifyScore,
    precolor: PrecolorDistance,
    target: tuple[int, ...],
    alpha: float,
) -> float:
    """Combined-score scalar from already-computed components.

    Single source of truth for the combined-score formula. Callers that
    already hold `SimplifyScore` and `PrecolorDistance` should use this
    instead of `combined_score`, which re-extracts both from raw
    `BaselineSignature` objects.

    `simplify_progress_ratio = common_prefix_length / len(target)` (in [0,1]
    when target is non-empty); ratio is 0.0 when target is empty. Combined
    = ratio − alpha × distance.total.
    """
    target_len = len(target)
    ratio = (simplify_score.common_prefix_length / target_len) if target_len else 0.0
    return ratio - alpha * precolor.total


def combined_score(
    baseline: BaselineSignature,
    candidate: BaselineSignature,
    target: tuple[int, ...],
    *,
    alpha: float = DEFAULT_COMBINED_ALPHA,
) -> CombinedScore:
    """Combined simplify-order progress and precolor-disturbance score.

    Combines `score_simplify_order` and `precolor_distance` into a single
    scalar that rewards simplify-order progress while penalizing precolor
    disturbance. Higher combined = better candidate.

    See `combined_value` for the formula; this entry point re-extracts
    `SimplifyScore` and `PrecolorDistance` from the raw signatures so
    callers don't have to compute them separately. The α default is
    `DEFAULT_COMBINED_ALPHA = 0.001`; see that constant's docstring for the
    calibration reasoning.
    """
    simp = score_simplify_order(baseline, candidate, target)
    dist = precolor_distance(baseline, candidate)
    return CombinedScore(
        simplify_score=simp,
        precolor_distance=dist,
        combined=combined_value(simp, dist, target, alpha),
    )


# ---------------------------------------------------------------------------
# Search driver
# ---------------------------------------------------------------------------


def _extract_signature_for(
    pcdump_text: str, function: str, *, class_id: int,
) -> BaselineSignature | None:
    """Parse pcdump text and pull the BaselineSignature for `function`.

    Returns None if the function isn't in the pcdump (so the caller can
    treat it as a compile-failure-equivalent).
    """
    events_list = parse_hook_events(pcdump_text)
    events = find_event_function(events_list, function)
    if events is None:
        return None
    return baseline_signature(events, class_id=class_id)


def search(
    sources: list[VariantSource],
    ctx: FunctionContext,
    baseline: BaselineSignature,
    target: tuple[int, ...],
    *,
    target_late: tuple[int, ...] = (),
    class_id: int = 0,
    max_candidates: int = 100,
    timeout: int = 60,
    preserve_precolor_enabled: bool = True,
    melee_root: Path | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> SearchResult:
    """Search source variants for one that produces the target simplify order.

    Args:
      sources: One or more `VariantSource`s. The driver walks them in order,
        consuming variants until either the cumulative compile count hits
        `max_candidates` or an exact match is found.
      ctx: Function under search. Adapters use this to know which file/unit
        to target, but the search driver itself only consumes `text`.
      baseline: Reference signature from the known-good pcdump. The gate
        rejects variants that differ on the three preserve components.
      target: ig_idx sequence the search wants at the head of simplify_order.
        Mutually exclusive with `target_late`.
      target_late: ig_idx sequence the search wants at the TAIL of
        simplify_order (late-mode, for ``--want-late``). When non-empty,
        suffix scoring is used instead of prefix scoring. Mutually exclusive
        with `target`.
      class_id: Which register class to score against. Defaults to 0 (GPR).
      max_candidates: Hard cap on variants compiled. Driver stops when the
        cumulative compile count reaches this — bounds wall-clock cost.
      timeout: Per-compile timeout passed down to `compile_source_variant`.
      preserve_precolor_enabled: When False, the gate is skipped (all variants
        with a parseable pcdump get scored). Default True.
      melee_root: Override the melee root used for compile. Defaults to
        `ctx.melee_root`.
      progress_callback: Optional callback invoked immediately before each
        compile with `(compiled_count, max_candidates, provenance)`.
    """
    melee_root = melee_root or ctx.melee_root
    start = time.time()
    progress: list[ScoredVariant] = []
    exact_match: SourceVariant | None = None
    rejected = 0
    rejection_reasons: list[str] = []
    seen_reasons: set[str] = set()
    rejected_scored: list[RejectedCandidate] = []
    compile_failures = 0
    compiled = 0
    # Cross-source dedup: if two adapters (or the same adapter twice) emit
    # the same `variant.text`, only compile it once. Per-adapter dedup
    # catches duplicates within one source; this catches collisions between
    # sources. Keyed off the full source text — adapters that change only
    # whitespace would still be considered distinct, but that's intentional
    # since MWCC's frontend can be whitespace-sensitive in subtle ways.
    seen_variant_texts: set[str] = set()

    for source in sources:
        if exact_match is not None:
            break
        for variant in source(ctx):
            if exact_match is not None:
                break
            # Dedup BEFORE incrementing `compiled` so duplicate texts don't
            # consume `max_candidates` slots — otherwise a noisy adapter
            # could starve the search by repeating the same variant.
            if variant.text in seen_variant_texts:
                continue
            seen_variant_texts.add(variant.text)
            if compiled >= max_candidates:
                break
            compiled += 1
            if progress_callback is not None:
                progress_callback(compiled, max_candidates, variant.provenance)

            try:
                pcdump_text = _compile_variant(variant, ctx=ctx, melee_root=melee_root, timeout=timeout)
            except CompileFailure:
                compile_failures += 1
                continue

            sig = _extract_signature_for(pcdump_text, ctx.function, class_id=class_id)
            if sig is None:
                # Pcdump exists but doesn't mention the function — treat
                # as a compile-equivalent failure rather than a gate
                # rejection, since the gate had no data to evaluate.
                compile_failures += 1
                continue

            # Always compute the score regardless of gate result. Gate-rejected
            # candidates still answer the diagnostic question "did permuter
            # ever produce a variant that moved simplify-order toward target,
            # even if it also disturbed precolor?" — so we want their score
            # too, not just the count.
            # In late-mode (target_late non-empty) use suffix scoring so
            # common_prefix_length tracks how many tail positions match.
            if target_late:
                score = _score_simplify_order_suffix(baseline, sig, target_late)
            else:
                score = score_simplify_order(baseline, sig, target)
            # Compute precolor_distance unconditionally too. When the gate is
            # on and a candidate passes, the distance is structurally zero
            # (the gate passes iff all three preserve components match), but
            # we attach it anyway for uniformity with the gate-off case and
            # so the rank-combined ranking path doesn't need to special-case
            # passing vs rejected.
            dist = precolor_distance(baseline, sig)

            if preserve_precolor_enabled:
                gate = preserve_precolor(baseline, sig)
                if not gate.passed:
                    rejected += 1
                    if gate.reason not in seen_reasons:
                        seen_reasons.add(gate.reason)
                        if len(rejection_reasons) < 8:
                            rejection_reasons.append(gate.reason)
                    rejected_scored.append(RejectedCandidate(
                        provenance=variant.provenance,
                        score=score,
                        rejection_reason=gate.reason,
                        precolor_distance=dist,
                    ))
                    continue

            scored = ScoredVariant(
                variant=variant, signature=sig, score=score,
                precolor_distance=dist,
            )

            if score.is_exact_match:
                exact_match = variant
                break

            if score.common_prefix_length > score.baseline_common_prefix_length:
                progress.append(scored)

    progress.sort(key=lambda sv: sv.score.common_prefix_length, reverse=True)

    return SearchResult(
        exact_match=exact_match,
        progress=progress,
        gate_rejected_count=rejected,
        gate_rejection_reasons=rejection_reasons,
        rejected_scored=rejected_scored,
        compile_failure_count=compile_failures,
        total_compiles=compiled,
        elapsed_seconds=time.time() - start,
    )


def _compile_variant(
    variant: SourceVariant,
    *,
    ctx: FunctionContext,
    melee_root: Path,
    timeout: int,
) -> str:
    """Write the variant to a temp .c file and shell out to dump local."""
    with tempfile.TemporaryDirectory(prefix="mwcc_simplify_") as td:
        tmp_src = Path(td) / "variant.c"
        tmp_src.write_text(variant.text, encoding="utf-8")
        diff_input = DiffInput(
            label="V",
            token=str(tmp_src),
            kind="source",
            path=tmp_src,
        )
        return compile_source_variant(
            diff_input,
            function=ctx.function,
            melee_root=melee_root,
            timeout=timeout,
        )
