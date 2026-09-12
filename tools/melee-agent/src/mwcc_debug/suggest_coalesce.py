# tools/melee-agent/src/mwcc_debug/suggest_coalesce.py
"""Orchestrator + renderer for `debug suggest coalesce`.

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
    CascadeCandidate, IrFacts, _callee_saves, analyze_cascade, collect,
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
    register_class: str = "gpr"


@dataclass
class Report:
    """Full orchestration result; rendered to text or JSON by callers."""
    function: str
    mode: str  # "pair" | "discover"
    cascade: Optional[list[int]] = None
    pairs: list[PairReport] = field(default_factory=list)
    register_class: str = "gpr"
    target_source: str = "--pair"
    source_shape_summary: Optional[dict] = None


def run(
    function: str,
    *,
    pair: Optional[tuple[int, int]] = None,
    discover: bool = False,
    top: int = 3,
    include_low_confidence: bool = False,
    register_class: str = "gpr",
    target_source: str = "--pair",
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

    register_kind = _register_kind(register_class)
    normalized_register_class = _register_class_name(register_kind)
    facts = collect(fn, source_text, register_kind=register_kind)
    if facts.pre_pass.name == "(missing)":
        raise ValueError(
            f"no pre-coloring pass for {function!r}; pcdump lacks IR detail"
        )

    # Hook events for colorgraph data (discover mode needs this)
    if discover:
        events_list = parse_hook_events(pcdump_text)
        evs = find_function(events_list, function)
        if evs and evs.colorgraph_sections:
            facts.cg_section = _select_colorgraph_section(
                evs.colorgraph_sections,
                register_kind=register_kind,
            )

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
            callee_saves = set(_callee_saves(facts))
            chain = sorted(
                {d.assigned_reg for d in facts.cg_section.decisions
                 if d.assigned_reg in callee_saves},
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
            facts.cg_section = _select_colorgraph_section(
                evs.colorgraph_sections,
                register_kind=register_kind,
            )

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
            register_class=normalized_register_class,
        ))

    return Report(
        function=function,
        mode="discover" if discover else "pair",
        cascade=cascade,
        pairs=pair_reports,
        register_class=normalized_register_class,
        target_source=target_source,
    )


def _register_kind(register_class: str) -> str:
    key = register_class.strip().lower()
    if key in {"f", "fp", "fpr", "float", "1"}:
        return "f"
    return "r"


def _register_class_name(register_kind: str) -> str:
    return "fpr" if register_kind == "f" else "gpr"


def _register_class_id(register_kind: str) -> int:
    return 1 if register_kind == "f" else 0


def _select_colorgraph_section(sections, *, register_kind: str):
    class_id = _register_class_id(register_kind)
    return next(
        (section for section in sections if section.class_id == class_id),
        sections[0] if sections else None,
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
    prefix = _prefix_for_facts(facts)
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
    missing_nodes = [v for v in (a, b) if v not in interferer_map]
    if missing_nodes:
        missing = ", ".join(f"{prefix}{v}" for v in missing_nodes)
        reasons.append(
            f"missing colorgraph node(s): {missing} — virtual may be "
            f"simplify-only or pcode-only, so forced coalesce is unsafe"
        )
    if (
        a in interferer_map.get(b, set())
        or b in interferer_map.get(a, set())
    ):
        reasons.append(
            f"virtuals interfere directly per colorgraph data — coalesce "
            f"is invalid (forcing it may hang the allocator)"
        )

    if a >= 32 and b >= 32 and not _has_direct_copy_edge(facts, a, b):
        reasons.append(
            f"no direct copy/identity edge between {prefix}{a} and {prefix}{b} in "
            f"pre-coloring IR — non-interfering but unsafe to force; "
            f"treat this as a source-shape lead, not a --force-coalesce "
            f"proof"
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


def _has_direct_copy_edge(facts: IrFacts, a: int, b: int) -> bool:
    """Return True if pre-coloring IR contains a cheap copy a<->b edge."""
    targets = {(a, b), (b, a)}
    for _block_idx, _idx, inst in facts.pre_pass.all_instructions():
        regs = [
            (kind, num)
            for kind, num in inst.regs
            if kind == facts.register_kind
        ]
        if len(regs) < 2:
            continue
        dst = regs[0][1]
        src = regs[1][1]
        if (dst, src) not in targets:
            continue
        if facts.register_kind == "f" and inst.opcode == "fmr":
            return True
        if facts.register_kind == "r" and inst.opcode == "mr":
            return True
        if facts.register_kind == "r" and inst.opcode == "addi":
            parts = [part.strip() for part in inst.operands.split(",")]
            if len(parts) >= 3 and parts[2] == "0":
                return True
        if facts.register_kind == "r" and inst.opcode == "or" and len(regs) >= 3:
            rhs2 = regs[2][1]
            if src == rhs2:
                return True
    return False


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
        entry["register_class"] = _register_class_name(facts.register_kind)
        if vf and vf.first_def:
            entry["first_def"] = {
                "block": vf.first_def.block_idx,
                "opcode": vf.first_def.opcode,
                "operands": vf.first_def.operands,
            }
            entry["use_blocks"] = sorted({bi for (bi, _) in vf.use_sites})
        # Source-line annotation from bridge bindings, gated by confidence.
        if facts.register_kind == "r":
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
        "register_class": report.register_class,
        "target_source": report.target_source,
        "cascade": report.cascade,
        "pairs": [
            {
                "from": p.from_virt,
                "to": p.to_virt,
                "register_class": p.register_class,
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
    if report.source_shape_summary is not None:
        payload["source_shape_summary"] = report.source_shape_summary
    return json.dumps(payload, indent=2)


def render_text(report: Report) -> str:
    """Render Report as human-readable text."""
    lines: list[str] = []
    lines.append(f"suggest-coalesce-source — {report.function}  "
                 f"{'--discover' if report.mode == 'discover' else 'pair'}")
    if report.mode == "discover" and report.cascade:
        prefix = _prefix_for_class(report.register_class)
        cas_str = " → ".join(f"{prefix}{r}" for r in report.cascade)
        lines.append(f"")
        lines.append(f"Longest callee-save cascade: {cas_str}")
        lines.append(f"  ({len(report.cascade)} saved regs)")
    if report.source_shape_summary is not None:
        summary = report.source_shape_summary
        lines.append("")
        lines.append("Source-shape continuation:")
        lines.append(
            "  "
            f"{summary.get('status')}: {summary.get('source_expression') or '?'} "
            f"-> {summary.get('assigned_local') or '?'}"
        )
        families = summary.get("candidate_families")
        if isinstance(families, list) and families:
            lines.append("  families: " + ", ".join(str(item) for item in families))
        next_command = summary.get("next_command")
        if isinstance(next_command, str) and next_command:
            lines.append(f"  next: {next_command}")
    lines.append("")
    for p in report.pairs:
        prefix = _prefix_for_class(p.register_class)
        header = f"pair {prefix}{p.from_virt}={prefix}{p.to_virt}"
        if p.priority_class:
            header += f"   [{p.priority_class}]"
            if p.depends_on:
                d_from, d_to = p.depends_on
                header += f" depends_on {prefix}{d_from}={prefix}{d_to}"
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
            entry_prefix = _prefix_for_class(
                str(entry.get("register_class") or p.register_class)
            )
            kind = "physical reg" if entry["is_phys"] else f"{entry_prefix}{v}"
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
                        f"       Catalog: debug util patterns {s.catalog_ref}"
                    )
        else:
            lines.append("  No specific pattern matched. Raw IR facts above —")
            lines.append("  search the C source for places where the bindings")
            lines.append("  of both virtuals could share an assignment or")
            lines.append("  expression. Catalog: debug util patterns "
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
        prefix = _prefix_for_class(str(entry.get("register_class") or "gpr"))
        if first_def:
            lines.append(
                f"    {prefix}{v} "
                "(compiler temp): "
                f"def block B{first_def['block']} "
                f"`{first_def['opcode']} {first_def['operands']}`"
            )
        else:
            lines.append(f"    {prefix}{v} (compiler temp): no first-def in pre-pass")
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


def _prefix_for_facts(facts: IrFacts) -> str:
    return "f" if facts.register_kind == "f" else "r"


def _prefix_for_class(register_class: str) -> str:
    key = register_class.strip().lower()
    return "f" if key in {"f", "fp", "fpr", "float", "1"} else "r"
