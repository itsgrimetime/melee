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


def _color_order_detail(
    virtual: int,
    blockers: list[int],
    simplify_by_ig: dict[int, object],
) -> str:
    """Explain the observed simplify/color order for a one-blocker swap."""
    if len(blockers) != 1:
        return ""
    blocker = blockers[0]
    entry = simplify_by_ig.get(virtual)
    blocker_entry = simplify_by_ig.get(blocker)
    if entry is None or blocker_entry is None:
        return ""

    entry_iter = getattr(entry, "iter_idx", "?")
    entry_degree = getattr(entry, "degree", "?")
    entry_n_intfr = getattr(entry, "array_size", "?")
    blocker_iter = getattr(blocker_entry, "iter_idx", "?")
    blocker_degree = getattr(blocker_entry, "degree", "?")
    blocker_n_intfr = getattr(blocker_entry, "array_size", "?")

    try:
        delta = abs(int(blocker_n_intfr) - int(entry_n_intfr)) + 1
    except (TypeError, ValueError):
        delta = 1

    return (
        f" Color-order detail: r{virtual} iter={entry_iter}, "
        f"degree={entry_degree}, nIntfr={entry_n_intfr}; "
        f"r{blocker} iter={blocker_iter}, degree={blocker_degree}, "
        f"nIntfr={blocker_n_intfr}. To bias r{virtual} before r{blocker}, "
        f"try source changes that reduce r{blocker} nIntfr by at least "
        f"{delta} or increase r{virtual} nIntfr by at least {delta}, then "
        f"verify the order with `debug dump local <c_file> "
        f"--force-iter-first {virtual},{blocker} --force-iter-first-fn <fn>` "
        f"or `debug target match-iter-first -f <fn> <pcdump>`."
    )


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
            order_detail = _color_order_detail(v, sorted(blockers), simplify_by_ig)
            suggestions.append(Suggestion(
                virtual=v, category="interference",
                description=(
                    f"r{v} wants r{tgt_phys} but r{tgt_phys} is taken by "
                    f"interfering virtual(s) {blockers_str}. Try: shrink "
                    f"the live range of {blockers_str} so they don't overlap "
                    f"r{v}, or move r{v}'s definition earlier so it's "
                    f"colored before {blockers_str}."
                    f"{order_detail}"
                ),
                severity="medium" if len(blockers) == 1 else "high",
            ))
            continue

        # No direct blocker. Check for the param-iter-ceiling pattern:
        # a low-ig_idx virtual (parameter-like) wants a high callee-save
        # that's held by a HIGHER-ig_idx virtual (local). Descending
        # ig_idx iteration order means the local was colored first.
        # This is an allocator-order mismatch — surface it with the
        # catalog pattern name so the agent switches workflow.
        owner_of_target: Optional[int] = None
        owner_ig_idx: Optional[int] = None
        for other_virt, other in infos.items():
            if other.physical == tgt_phys and other_virt != v:
                owner_of_target = other_virt
                owner_ig_idx = other_virt  # virtual num == ig_idx for IG nodes
                break

        # Heuristic: parameter virtuals are typically the LOWEST-numbered.
        # 32-34 is a safe band (covers args0-args2 in PowerPC EABI).
        # If our wrong virtual is in that band AND a higher-numbered
        # virtual owns the target physical, it's the param-iter-ceiling.
        is_param_like = v <= 34
        local_owns_target = (
            owner_of_target is not None and owner_of_target > v
        )

        if is_param_like and local_owns_target:
            suggestions.append(Suggestion(
                virtual=v, category="param-iter-ceiling",
                description=(
                    f"r{v} (low ig_idx, parameter-like) wants r{tgt_phys}, "
                    f"but r{tgt_phys} is held by r{owner_of_target} "
                    f"(higher ig_idx, local). MWCC simplifygraph iterates "
                    f"the IG in DESCENDING ig_idx order, so r{owner_of_target} "
                    f"is colored first and grabs r{tgt_phys}. r{v} gets "
                    f"r{actual_phys} from whatever's left. This is a "
                    f"Tier 6 allocator-order mismatch; it is unresolved by "
                    f"current heuristics rather than proof that C-source "
                    f"edits cannot work. Confirm via "
                    f"`debug inspect rank-callees -f <fn>` (shows the cascade). "
                    f"Three ways to verify the target is reachable:\n"
                    f"      (a) `debug dump local <c_file> "
                    f"--force-iter-first {v} --force-iter-first-fn <fn>` — "
                    f"safest, pure iter-order change, no IG mutation.\n"
                    f"      (b) `debug dump local <c_file> "
                    f"--force-coalesce '{v}={owner_of_target}'` — merge "
                    f"param into the local that wins the phys; if matches, "
                    f"search for natural-coalesce C patterns (moves, "
                    f"common subexprs).\n"
                    f"      (c) `debug dump local <c_file> --force-phys "
                    f"'{v}:{tgt_phys},{owner_of_target}:{actual_phys}'` — "
                    f"hard override, may produce incorrect code (last resort).\n"
                    f"      If any of these matches: record as Tier 6 "
                    f"allocator-order evidence + try source-shape search "
                    f"(`debug permute run -f <fn>`)."
                ),
                severity="high",
            ))
            continue

        # Generic rank issue — no direct blocker but also not the param
        # allocator-order family. Could be a smaller iteration-order rearrange the agent
        # might fix with decl-order tricks. Could also be a coalesce gap —
        # MWCC may have failed to merge two virtuals that COULD share a
        # phys (e.g. a short-lived `sel = 0` virtual + loop counter init).
        candidates_str = (
            ", ".join(f"r{c}" for c in sorted(info.candidates)[:8])
            if info.candidates else "(none)"
        )
        # Find any virtual currently using r{tgt_phys} — candidate to
        # hypothesis-test a coalesce-merge with via --force-coalesce.
        coalesce_hint = ""
        for owner_v, owner_info in infos.items():
            if owner_v == v:
                continue
            if owner_info.physical == tgt_phys:
                coalesce_hint = (
                    f" If they shouldn't both live (e.g. one is a brief "
                    f"`sel = 0`), hypothesis-test with `debug dump local "
                    f"<c_file> --force-coalesce '{v}={owner_v}'` — if .text "
                    f"matches, look for a C-source pattern that makes MWCC "
                    f"naturally coalesce them (move instruction, common "
                    f"subexpression, alias variable)."
                )
                break
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
                f"r{tgt_phys} earlier." + coalesce_hint
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
    from the catalog after each suggestion. Use `debug util patterns
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
                    f"     (run `melee-agent debug util patterns <name>` "
                    f"for examples)"
                )
    return "\n".join(out)
