"""Heuristic guidance suggestions for nudging a stuck function's coloring.

Reads the pcdump diagnostic output (analyze + simplify section) and emits
human-readable suggestions for what to try in C source. These are NOT
guarantees — they're hints based on common patterns. The matching agent
(human or LLM) should interpret them in source context.

Tier 4 v1 — see docs/mwcc-debug-tier4-permuter.md for design notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .colorgraph_parser import FunctionEvents
from .parser import Function, VirtualRegInfo, analyze_function
from .patterns import PATTERNS, patterns_for_category
from .scoring import ScoreBreakdown


@dataclass
class Suggestion:
    """One actionable nudge for the human reviewer."""

    virtual: int  # which virtual reg this concerns
    category: str  # "interference" / "spill" / "rank" / "missing"
    description: str  # human-readable
    severity: str  # "high" / "medium" / "low" — for ordering
    patterns: list[str] = None  # type: ignore[assignment]
    # ^ list of pattern names from the catalog that might apply.
    # Populated by suggest() based on category. Use format_suggestions()
    # to render with pattern hints inlined.

    def __post_init__(self) -> None:
        if self.patterns is None:
            self.patterns = []


def suggest(
    fn: Function,
    breakdown: ScoreBreakdown,
    events: Optional[FunctionEvents] = None,
) -> list[Suggestion]:
    """Generate a ranked list of suggestions for fixing wrong virtuals."""
    suggestions: list[Suggestion] = []
    infos = {v.virtual: v for v in analyze_function(fn)}

    # Map ig_idx -> simplify entry for fast lookup
    simplify_by_ig: dict[int, object] = {}
    if events is not None:
        for sec in events.simplify_sections:
            for entry in sec.entries:
                if entry.ig_idx >= 0:
                    simplify_by_ig[entry.ig_idx] = entry

    for v, tgt_phys, actual_phys in breakdown.wrong:
        info = infos.get(v)
        if info is None:
            suggestions.append(Suggestion(
                virtual=v, category="missing",
                description=(
                    f"Target wants r{v} → r{tgt_phys}, but no virtual r{v} "
                    f"appears in this pcdump. Did a structural change "
                    f"renumber the virtuals?"
                ),
                severity="high",
            ))
            continue

        # Did this virtual carry a SPILLED marker from simplifygraph?
        simplify_entry = simplify_by_ig.get(v)
        if simplify_entry is not None and getattr(simplify_entry, "spilled", False):
            suggestions.append(Suggestion(
                virtual=v, category="spill",
                description=(
                    f"r{v} (target r{tgt_phys}, actual r{actual_phys}) was "
                    f"marked SPILLED by simplifygraph (degree "
                    f"{simplify_entry.array_size} ≥ n_colors). To unblock: "
                    f"reduce r{v}'s interferer count below the available "
                    f"physical-register count by shrinking its live range "
                    f"(declare later, use sooner) or by reducing the "
                    f"number of simultaneously-live other virtuals."
                ),
                severity="high",
            ))
            continue

        # Find which interferer is blocking the target physical
        blockers: list[int] = []
        for other_v in info.interferes_with:
            other = infos.get(other_v)
            if other is None or other.physical is None:
                continue
            if other.physical == tgt_phys:
                blockers.append(other_v)

        if blockers:
            blockers_str = ", ".join(f"r{b}" for b in sorted(blockers))
            suggestions.append(Suggestion(
                virtual=v, category="interference",
                description=(
                    f"r{v} wants r{tgt_phys} but r{tgt_phys} is taken by "
                    f"interfering virtual(s) {blockers_str}. Try: shrink "
                    f"the live range of {blockers_str} so they don't overlap "
                    f"r{v}, or move r{v}'s definition earlier so it's "
                    f"colored before {blockers_str}."
                ),
                severity="medium" if len(blockers) == 1 else "high",
            ))
            continue

        # No direct blocker — virtual got an unexpected scratch reg, perhaps
        # because its interferer count is too low (not seen as nonvolatile-
        # worthy) or because iteration order put it at a bad slot.
        candidates_str = (
            ", ".join(f"r{c}" for c in sorted(info.candidates)[:8])
            if info.candidates else "(none)"
        )
        suggestions.append(Suggestion(
            virtual=v, category="rank",
            description=(
                f"r{v} (target r{tgt_phys}, actual r{actual_phys}) has no "
                f"direct interferer at r{tgt_phys}, so the allocator could "
                f"have picked r{tgt_phys} but chose r{actual_phys}. This "
                f"usually means the simplification order put r{v} at a "
                f"lower-priority slot. Candidates the allocator saw: "
                f"{{{candidates_str}}}. Try: increase r{v}'s degree (more "
                f"interferences) to push it up the simplification stack, "
                f"or shrink the lifetime of other virtuals that consumed "
                f"r{tgt_phys} earlier."
            ),
            severity="low",
        ))

    # Always include SPILLED warnings even for virtuals not in the wrong list,
    # since they signal structural difficulty regardless of current allocation.
    for ig_idx in breakdown.spill_unexpected:
        if not any(s.virtual == ig_idx for s in suggestions):
            entry = simplify_by_ig.get(ig_idx)
            if entry is None:
                continue
            suggestions.append(Suggestion(
                virtual=ig_idx, category="spill",
                description=(
                    f"r{ig_idx} carries SPILLED flag (degree "
                    f"{entry.array_size}, n_colors=N from simplify section). "
                    f"Even though current mapping matches target, this "
                    f"virtual is on the edge — small source changes could "
                    f"tip it over. Consider reducing its interferer count "
                    f"for stability."
                ),
                severity="low",
            ))

    # Attach pattern hints. Each suggestion's category maps to one or
    # more patterns from the catalog (see patterns.py:addresses).
    for s in suggestions:
        s.patterns = [p.name for p in patterns_for_category(s.category)]

    # Order by severity (high first), then by virtual number
    severity_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: (severity_order.get(s.severity, 3), s.virtual))
    return suggestions


def format_suggestions(suggestions: list[Suggestion], with_patterns: bool = True) -> str:
    """Render suggestions as a human-readable report.

    If `with_patterns` is True (default), include named pattern hints
    from the catalog after each suggestion. Use `debug pattern-catalog
    <name>` to see the full pattern description + example.
    """
    if not suggestions:
        return "No issues found — current coloring matches target."
    out = []
    for s in suggestions:
        marker = {"high": "!!", "medium": "!", "low": "·"}.get(s.severity, " ")
        out.append(f"  {marker} [r{s.virtual} / {s.category}] {s.description}")
        if with_patterns and s.patterns:
            pattern_titles = []
            for name in s.patterns:
                p = PATTERNS.get(name)
                if p is not None:
                    pattern_titles.append(f"`{p.name}` ({p.title})")
            if pattern_titles:
                out.append(
                    f"     Patterns to try: {', '.join(pattern_titles)}"
                )
                out.append(
                    f"     (run `melee-agent debug pattern-catalog <name>` "
                    f"for examples)"
                )
    return "\n".join(out)
