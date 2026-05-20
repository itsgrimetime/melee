# tools/melee-agent/src/mwcc_debug/suggest_coalesce.py
"""Orchestrator + renderer for `debug suggest-coalesce-source`.

Composes the IR-facts layer + per-pattern checkers + (in discover mode)
the cascade analyzer into a Report, then renders human-readable text
or JSON. The CLI thin-wraps this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .coalesce_ir_facts import (
    CascadeCandidate, IrFacts, analyze_cascade, collect,
)
from .coalesce_patterns import ALL_PATTERNS, Suggestion
from .colorgraph_parser import find_function, parse_hook_events
from .parser import parse_pcdump


@dataclass
class Preflight:
    """Cheap safety check for a candidate coalesce pair.

    `safe=True` means the pair passes all known-dangerous-pattern checks
    (does NOT mean coalescing will improve the match — only that it is
    structurally valid). `reasons` lists every failed check, so the
    user/agent sees ALL dangers up front instead of triggering them
    sequentially.

    Checks currently performed (all O(degree) against cg_section data):
      - `interferes`: virtuals interfere directly (per colorgraph data).
        Forcing this coalesce can hang or crash the allocator.
      - `physical_reg`: one or both virtuals are actually physical-reg
        sentinels (< 32). Coalescing into a phys-reg slot is meaningless.
      - `cross_class`: the two virtuals belong to different IG classes
        (e.g. GPR + FP). MWCC's coalescer can't fuse cross-class nodes.
      - `missing_cg_section`: no colorgraph data was available; the
        check is best-effort — caller should treat `safe=True` here as
        "untested, not necessarily safe".
    """
    safe: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class PairReport:
    """One proposed pair plus its IR evidence and ranked suggestions."""
    from_virt: int
    to_virt: int
    ir_facts: dict
    suggestions: list[Suggestion]
    priority_class: Optional[str] = None
    depends_on: Optional[tuple[int, int]] = None
    preflight: Optional[Preflight] = None


@dataclass
class Report:
    """Full orchestration result; rendered to text or JSON by callers."""
    function: str
    mode: str  # "pair" | "discover"
    cascade: Optional[list[int]] = None
    pairs: list[PairReport] = field(default_factory=list)


def run(
    function: str,
    *,
    pair: Optional[tuple[int, int]] = None,
    discover: bool = False,
    top: int = 3,
    include_low_confidence: bool = False,
    pcdump_text: str,
    source_text: str = "",
) -> Report:
    """Build a Report for `function`.

    The CLI is responsible for resolving pcdump + source paths and
    passing their contents in. Keeping this module path-free avoids a
    backward import on cli.debug (which would create a circular
    dependency since cli.debug already imports this module).

    Exactly one of `pair` or `discover` must be set — the CLI
    enforces this.
    """
    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        raise ValueError(f"function {function!r} not in pcdump")

    facts = collect(fn, source_text)
    if facts.pre_pass.name == "(missing)":
        raise ValueError(
            f"no pre-coloring pass for {function!r}; pcdump lacks IR detail"
        )

    # Hook events for colorgraph data (discover mode needs this)
    if discover:
        events_list = parse_hook_events(pcdump_text)
        evs = find_function(events_list, function)
        if evs and evs.colorgraph_sections:
            facts.cg_section = evs.colorgraph_sections[0]

    # Resolve pairs to evaluate
    if pair is not None:
        pairs_to_check: list[tuple[int, int, Optional[CascadeCandidate]]] = [
            (pair[0], pair[1], None)
        ]
        cascade: Optional[list[int]] = None
    else:
        cands = analyze_cascade(facts)[:top]
        pairs_to_check = [(c.from_virt, c.to_virt, c) for c in cands]
        # Build the cascade summary list (descending phys regs)
        if facts.cg_section is not None:
            chain = sorted(
                {d.assigned_reg for d in facts.cg_section.decisions
                 if 25 <= d.assigned_reg <= 31},
                reverse=True,
            )
            cascade = chain if len(chain) >= 2 else None
        else:
            cascade = None

    # Pair mode usually doesn't pull `cg_section` (the caller only sets
    # it in discover branch above). But our preflight needs the
    # colorgraph data for both modes. Lazily populate it here so a `-V`
    # user gets interference/cross-class checks too.
    if not discover and facts.cg_section is None:
        events_list = parse_hook_events(pcdump_text)
        evs = find_function(events_list, function)
        if evs and evs.colorgraph_sections:
            facts.cg_section = evs.colorgraph_sections[0]

    # Run pattern checkers per pair
    pair_reports: list[PairReport] = []
    for a, b, cand in pairs_to_check:
        suggestions: list[Suggestion] = []
        for pat in ALL_PATTERNS:
            sug = pat.check(facts, (a, b))
            if sug is not None:
                suggestions.append(sug)
        preflight = _preflight_pair(facts, a, b, pcdump_text=pcdump_text)
        pair_reports.append(PairReport(
            from_virt=a, to_virt=b,
            ir_facts=_summarize_facts(
                facts, a, b,
                include_low_confidence=include_low_confidence,
            ),
            suggestions=suggestions,
            priority_class=cand.priority_class if cand else None,
            depends_on=cand.depends_on if cand else None,
            preflight=preflight,
        ))

    return Report(
        function=function,
        mode="discover" if discover else "pair",
        cascade=cascade,
        pairs=pair_reports,
    )


def _preflight_pair(
    facts: IrFacts, a: int, b: int, *, pcdump_text: str = "",
) -> Preflight:
    """Cheap pre-check on a coalesce candidate `a=b`.

    Catches the common dangerous patterns BEFORE the user spends 45s on
    a `pcdump-local --force-coalesce` that ends in a watchdog kill. See
    `Preflight` for the catalog of checks.

    pcdump_text is optional and used only for the cross-class probe
    (which needs to enumerate all classes' colorgraph sections, not
    just `facts.cg_section`).
    """
    reasons: list[str] = []

    # physical-reg check — < 32 means MWCC pre-coloring slot, not a
    # coalesceable virtual.
    if a < 32 or b < 32:
        reasons.append(
            f"one or both nodes are physical regs "
            f"(a={a}{'(phys)' if a < 32 else ''}, "
            f"b={b}{'(phys)' if b < 32 else ''})"
        )

    cg = facts.cg_section
    if cg is None:
        # Surface the absence: caller should treat this as "untested".
        reasons.append(
            "no colorgraph data — interference / class checks skipped"
        )
        return Preflight(safe=not reasons, reasons=reasons)

    # interference: build a lookup of (ig_idx -> set(interferer ig_idx))
    interferer_map: dict[int, set[int]] = {}
    for d in cg.decisions:
        interferer_map[d.ig_idx] = {ig for (ig, _) in d.interferers}
    if (
        a in interferer_map.get(b, set())
        or b in interferer_map.get(a, set())
    ):
        reasons.append(
            f"virtuals interfere directly per colorgraph data — coalesce "
            f"is invalid (forcing it may hang the allocator)"
        )

    # cross-class detection — enumerate ALL colorgraph sections, since
    # facts.cg_section only carries one. If a and b live in different
    # classes, the coalesce is structurally invalid.
    if pcdump_text:
        try:
            events_list = parse_hook_events(pcdump_text)
            ev = find_function(events_list, facts.function_name)
            if ev is not None and ev.colorgraph_sections:
                class_of: dict[int, list[int]] = {}
                for sec in ev.colorgraph_sections:
                    for d in sec.decisions:
                        class_of.setdefault(d.ig_idx, []).append(sec.class_id)
                a_classes = set(class_of.get(a, []))
                b_classes = set(class_of.get(b, []))
                # If both are non-empty and disjoint, that's cross-class.
                if a_classes and b_classes and a_classes.isdisjoint(b_classes):
                    reasons.append(
                        f"cross-class coalesce — a in class(es) "
                        f"{sorted(a_classes)}, b in class(es) "
                        f"{sorted(b_classes)} (cross-class fuse is "
                        f"structurally invalid)"
                    )
        except Exception:
            # Best-effort; don't add a reason for the failure mode itself.
            pass

    return Preflight(safe=not reasons, reasons=reasons)


def _summarize_facts(
    facts: IrFacts, a: int, b: int,
    *, include_low_confidence: bool = False,
) -> dict:
    """Serializable per-virtual fact summary for JSON + text output.

    Source-line annotations from the bridge are only emitted when the
    binding confidence is best-guess/verified (or low-confidence with
    the explicit opt-in). Lower-confidence bindings are dropped from
    the summary — agents shouldn't act on potentially-wrong mappings.
    """
    out: dict = {}
    accepted = {"best-guess", "verified"}
    if include_low_confidence:
        accepted = accepted | {"low-confidence"}
    for label, v in [("from", a), ("to", b)]:
        vf = facts.by_virtual.get(v)
        entry: dict = {"virtual": v, "is_phys": vf.is_phys if vf else False}
        if vf and vf.first_def:
            entry["first_def"] = {
                "block": vf.first_def.block_idx,
                "opcode": vf.first_def.opcode,
                "operands": vf.first_def.operands,
            }
            entry["use_blocks"] = sorted({bi for (bi, _) in vf.use_sites})
        # Source-line annotation from bridge bindings, gated by confidence.
        for binding in facts.bindings:
            if binding.virtual == v and binding.confidence in accepted:
                entry["bridge"] = {
                    "var": binding.var_name,
                    "line": binding.decl_line,
                    "confidence": binding.confidence,
                }
                break
        out[label] = entry
    return out


def render_json(report: Report) -> str:
    """Render Report as parseable JSON."""
    payload = {
        "function": report.function,
        "mode": report.mode,
        "cascade": report.cascade,
        "pairs": [
            {
                "from": p.from_virt,
                "to": p.to_virt,
                "priority_class": p.priority_class,
                "depends_on": list(p.depends_on) if p.depends_on else None,
                "ir_facts": p.ir_facts,
                "suggestions": [
                    {
                        "pattern": s.pattern_name,
                        "summary": s.summary,
                        "ir_evidence": s.ir_evidence,
                        "source_hint": s.source_hint,
                        "catalog_ref": s.catalog_ref,
                    } for s in p.suggestions
                ],
                "preflight": (
                    {"safe": p.preflight.safe, "reasons": p.preflight.reasons}
                    if p.preflight is not None else None
                ),
            } for p in report.pairs
        ],
    }
    return json.dumps(payload, indent=2)


def render_text(report: Report) -> str:
    """Render Report as human-readable text."""
    lines: list[str] = []
    lines.append(f"suggest-coalesce-source — {report.function}  "
                 f"{'--discover' if report.mode == 'discover' else 'pair'}")
    if report.mode == "discover" and report.cascade:
        cas_str = " → ".join(f"r{r}" for r in report.cascade)
        lines.append(f"")
        lines.append(f"Longest callee-save cascade: {cas_str}")
        lines.append(f"  ({len(report.cascade)} saved regs)")
    lines.append("")
    for p in report.pairs:
        header = f"pair r{p.from_virt}=r{p.to_virt}"
        if p.priority_class:
            header += f"   [{p.priority_class}]"
            if p.depends_on:
                d_from, d_to = p.depends_on
                header += f" depends_on r{d_from}=r{d_to}"
        if p.preflight is not None and not p.preflight.safe:
            header += "   [PREFLIGHT: WARNING]"
        lines.append(header)
        if p.preflight is not None and not p.preflight.safe:
            for reason in p.preflight.reasons:
                lines.append(f"  ! {reason}")
        lines.append("")
        lines.append("  IR facts:")
        for label, entry in p.ir_facts.items():
            v = entry["virtual"]
            kind = "physical reg" if entry["is_phys"] else f"r{v}"
            line = f"    {kind}: "
            if "first_def" in entry:
                fd = entry["first_def"]
                line += f"defined block B{fd['block']} by `{fd['opcode']} {fd['operands']}`"
                if "use_blocks" in entry:
                    line += f"  [uses: {entry['use_blocks']}]"
            else:
                line += "no first-def found"
            lines.append(line)
            if "bridge" in entry:
                br = entry["bridge"]
                lines.append(
                    f"      bridge: {br['var']} @ line {br['line']} "
                    f"({br['confidence']})"
                )
        lines.append("")
        if p.suggestions:
            lines.append("  Suggestions (highest confidence first):")
            for i, s in enumerate(p.suggestions, 1):
                lines.append(f"    {i}. {s.pattern_name}")
                lines.append(f"       {s.summary}")
                lines.append(f"       evidence: {s.ir_evidence}")
                if s.source_hint:
                    lines.append(f"       try: {s.source_hint}")
                if s.catalog_ref:
                    lines.append(
                        f"       Catalog: debug pattern-catalog {s.catalog_ref}"
                    )
        else:
            lines.append("  No specific pattern matched. Raw IR facts above —")
            lines.append("  search the C source for places where the bindings")
            lines.append("  of both virtuals could share an assignment or")
            lines.append("  expression. Catalog: debug pattern-catalog "
                         "register-cascade")
            # Augment with use-site IR context for compiler temps (virtuals
            # with no bridge binding). Print the first few use-site
            # instructions so the agent can grep the pcdump instead of
            # doing it manually.
            _render_use_site_context(lines, p.ir_facts)
        lines.append("")
    return "\n".join(lines)


def _render_use_site_context(
    lines: list[str], ir_facts: dict, max_sites: int = 5
) -> None:
    """Append a 'Nearby IR (use-sites)' block for virtuals that have no
    high-confidence bridge binding (i.e. compiler temporaries).

    Only renders if at least one virtual in the pair lacks a bridge entry,
    to avoid redundancy when bridge context is already shown above.
    """
    any_temp = False
    for label in ("from", "to"):
        entry = ir_facts.get(label, {})
        if not entry.get("bridge") and not entry.get("is_phys"):
            any_temp = True
            break
    if not any_temp:
        return

    lines.append("")
    lines.append("  Nearby IR (use-sites):")
    for label in ("from", "to"):
        entry = ir_facts.get(label, {})
        v = entry.get("virtual", "?")
        bridge = entry.get("bridge")
        if bridge:
            # Bridge known — already shown above; skip.
            continue
        if entry.get("is_phys"):
            continue
        # use_sites_instructions is not in the serialized dict (it would
        # be redundant JSON). We rely on the text already printed for
        # first_def. Surface the use_blocks list + first_def as
        # "context" so the agent knows exactly which IR blocks to grep.
        first_def = entry.get("first_def")
        use_blocks = entry.get("use_blocks", [])
        if first_def:
            lines.append(
                f"    r{v} (compiler temp): "
                f"def block B{first_def['block']} "
                f"`{first_def['opcode']} {first_def['operands']}`"
            )
        else:
            lines.append(f"    r{v} (compiler temp): no first-def in pre-pass")
        if use_blocks:
            block_list = ", ".join(f"B{b}" for b in use_blocks[:max_sites])
            suffix = (f" (+{len(use_blocks) - max_sites} more)"
                      if len(use_blocks) > max_sites else "")
            lines.append(f"      used in blocks: {block_list}{suffix}")
        else:
            lines.append("      (no use-blocks recorded)")
        lines.append(
            "      → grep pcdump for these blocks to find the C statement"
        )
