"""Pass-by-pass diff reporting for mwcc-debug pcdumps."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .colorgraph_parser import (
    ColorgraphSection,
    FunctionEvents,
    find_function as find_event_function,
    parse_hook_events,
)
from .inspect_parser import InspectSnapshot, parse_inspect_snapshots
from .parser import Function, Pass, parse_pcdump


class DivergenceKind(str, Enum):
    TEXT = "text"
    META = "meta"
    RA_INTRINSIC = "ra-intrinsic"
    RA_INPUT_DERIVED = "ra-input-derived"


@dataclass(frozen=True)
class RADiff:
    classification: str
    input_changes: list[str] = field(default_factory=list)
    output_changes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PassDiff:
    index: int
    pass_name: str
    changed: bool
    kind: DivergenceKind | None = None
    summary: str = ""
    diff_lines: list[str] = field(default_factory=list)
    heuristic_causes: list[str] = field(default_factory=list)
    ra: RADiff | None = None
    cascade_from: int | None = None


@dataclass(frozen=True)
class DiffReport:
    function: str
    label_a: str
    label_b: str
    passes: list[PassDiff]
    earliest: PassDiff | None


def _format_pass_snapshot(pass_obj: Pass) -> str:
    lines: list[str] = [pass_obj.name]
    for block in pass_obj.blocks:
        succ = ",".join(f"B{i}" for i in block.succ)
        pred = ",".join(f"B{i}" for i in block.pred)
        labels = ",".join(block.labels)
        lines.append(f"B{block.index}: Succ={succ} Pred={pred} Labels={labels}")
        for inst in block.instructions:
            annot = ""
            if inst.annotations:
                annot = " ; " + "; ".join(inst.annotations)
            operands = f" {inst.operands}" if inst.operands else ""
            lines.append(f"    {inst.opcode}{operands}{annot}")
    return "\n".join(lines)


def _unified_diff(a: str, b: str, label_a: str, label_b: str, limit: int = 24) -> list[str]:
    lines = list(difflib.unified_diff(
        a.splitlines(),
        b.splitlines(),
        fromfile=label_a,
        tofile=label_b,
        lineterm="",
    ))
    return lines[:limit]


def _find_function_or_raise(text: str, function: str, label: str) -> Function:
    funcs = parse_pcdump(text, function=function)
    if not funcs:
        available = [fn.name for fn in parse_pcdump(text)]
        sample = ", ".join(available[:8])
        raise ValueError(
            f"function {function!r} not found in {label}; available: {sample}"
        )
    return funcs[0]


def _section_by_class(events: FunctionEvents | None, class_id: int) -> ColorgraphSection | None:
    if events is None:
        return None
    for section in events.colorgraph_sections:
        if section.class_id == class_id:
            return section
    return None


def _interference_edges(section: ColorgraphSection) -> set[tuple[int, int]]:
    """Set of normalized (min, max) interference edges for one class.

    Each ColorgraphDecision row carries an interferers list — pairs of
    (other_ig_idx, that_node's_assigned_reg). The IG is symmetric, so
    (a, b) and (b, a) are the same edge; we normalize to sorted order
    and deduplicate via set semantics.

    Self-edges (a == a) and stale -1 ig_idxs are dropped.
    """
    edges: set[tuple[int, int]] = set()
    for decision in section.decisions:
        if decision.ig_idx < 0:
            continue
        for other_idx, _reg in decision.interferers:
            if other_idx < 0 or other_idx == decision.ig_idx:
                continue
            lo, hi = sorted((decision.ig_idx, other_idx))
            edges.add((lo, hi))
    return edges


def _simplify_order(events: FunctionEvents | None, class_id: int) -> tuple[int, ...]:
    """Ordered ig_idx tuple from the simplify section, in iter_idx order.

    The parser appends entries in pcdump order, which is iter_idx order
    (the order nodes were pushed onto the simplification stack).
    """
    if events is None:
        return ()
    for section in events.simplify_sections:
        if section.class_id == class_id:
            return tuple(e.ig_idx for e in section.entries)
    return ()


def _coalesce_mappings(events: FunctionEvents | None, class_id: int) -> set[tuple[int, int]]:
    """Set of (virt, root) coalesce mappings for one class."""
    if events is None:
        return set()
    for section in events.coalesce_sections:
        if section.class_id == class_id:
            return set(section.mappings)
    return set()


def _spill_set(events: FunctionEvents | None, class_id: int) -> set[int]:
    """Set of ig_idxs that simplifygraph flagged as spilled (flags & 0x08).

    Note: this reads from SimplifyEntry (upstream input to the allocator),
    NOT from ColorgraphDecision.flags & 0x01 (which is set by the
    allocator itself and is therefore an output, not an input).
    """
    if events is None:
        return set()
    spilled: set[int] = set()
    for section in events.simplify_sections:
        if section.class_id == class_id:
            for entry in section.entries:
                if entry.spilled and entry.ig_idx >= 0:
                    spilled.add(entry.ig_idx)
    return spilled


def _ra_output_signature(section: ColorgraphSection) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (d.ig_idx, d.assigned_reg, d.flags)
        for d in sorted(section.decisions, key=lambda d: (d.ig_idx, d.iter_idx))
    )


def _summarize_tuple_diff(a: tuple[object, ...], b: tuple[object, ...], label: str) -> list[str]:
    """Summarize a generic tuple diff. Currently only used for coloring
    output (the RA output signature); the per-component RA *input* path
    has its own renderers in `_summarize_input_components`.
    """
    if a == b:
        return []
    if label.endswith("coloring output"):
        a_map = {item[0]: item[1:] for item in a if isinstance(item, tuple) and len(item) >= 3}
        b_map = {item[0]: item[1:] for item in b if isinstance(item, tuple) and len(item) >= 3}
        # Compute diffing keys FIRST, then cap. If we capped first, a function
        # with 30+ virtuals where only ig_idx 60-62 differ would emit just the
        # header line (the first 8 sorted keys all match) and silently lose the
        # actual diffs.
        diffing = [
            k
            for k in sorted(set(a_map) | set(b_map))
            if a_map.get(k) != b_map.get(k)
        ]
        # Cap detail lines at 7 so header + details + optional "...more" tail
        # totals at most 9, which fits the renderer's output_changes slice.
        lines = [f"{label} differs"]
        for key in diffing[:7]:
            lines.append(f"{label}: ig_idx {key}: {a_map.get(key)} -> {b_map.get(key)}")
        if len(diffing) > 7:
            lines.append(f"{label}: ... and {len(diffing) - 7} more")
        return lines
    return [f"{label} differs"]


_COMPONENT_DETAIL_CAP = 6


def _fmt_added_removed_pairs(
    added: list[tuple[int, int]],
    removed: list[tuple[int, int]],
) -> str:
    """Format `added: ...; removed: ...` clauses with a per-side cap.

    Each side caps at `_COMPONENT_DETAIL_CAP` entries plus a
    "... and N more" tail, mirroring the coloring-output expansion shape.
    """
    def _section(label: str, items: list[tuple[int, int]]) -> str:
        if not items:
            return f"{label}: none"
        shown = items[:_COMPONENT_DETAIL_CAP]
        rendered = ", ".join(f"({a}, {b})" for a, b in shown)
        if len(items) > _COMPONENT_DETAIL_CAP:
            rendered += f", ... and {len(items) - _COMPONENT_DETAIL_CAP} more"
        return f"{label}: {rendered}"

    return f"{_section('added', added)}; {_section('removed', removed)}"


def _fmt_added_removed_ints(added: list[int], removed: list[int], *, item_label: str) -> str:
    def _section(label: str, items: list[int]) -> str:
        if not items:
            return f"{label}: none"
        shown = items[:_COMPONENT_DETAIL_CAP]
        rendered = ", ".join(f"{item_label} {v}" for v in shown)
        if len(items) > _COMPONENT_DETAIL_CAP:
            rendered += f", ... and {len(items) - _COMPONENT_DETAIL_CAP} more"
        return f"{label}: {rendered}"

    return f"{_section('added', added)}; {_section('removed', removed)}"


def _interference_diff_line(
    class_id: int,
    edges_a: set[tuple[int, int]],
    edges_b: set[tuple[int, int]],
) -> str | None:
    if edges_a == edges_b:
        return None
    added = sorted(edges_b - edges_a)
    removed = sorted(edges_a - edges_b)
    return (
        f"class {class_id}: interference graph differs "
        f"({_fmt_added_removed_pairs(added, removed)})"
    )


def _coalesce_diff_line(
    class_id: int,
    mappings_a: set[tuple[int, int]],
    mappings_b: set[tuple[int, int]],
) -> str | None:
    if mappings_a == mappings_b:
        return None
    added = sorted(mappings_b - mappings_a)
    removed = sorted(mappings_a - mappings_b)
    return (
        f"class {class_id}: coalesce mappings differ "
        f"({_fmt_added_removed_pairs(added, removed)})"
    )


def _simplify_order_diff_line(
    class_id: int,
    order_a: tuple[int, ...],
    order_b: tuple[int, ...],
) -> str | None:
    """Find first divergence position in two simplify orders.

    Full lists are too noisy to render in a one-liner, so we emit only
    the first position where the orders disagree. Positions past the
    shorter list count as divergent (with a "no entry" placeholder).
    """
    if order_a == order_b:
        return None
    max_len = max(len(order_a), len(order_b))
    for pos in range(max_len):
        a_val = order_a[pos] if pos < len(order_a) else None
        b_val = order_b[pos] if pos < len(order_b) else None
        if a_val != b_val:
            a_str = f"ig_idx {a_val}" if a_val is not None else "no entry"
            b_str = f"ig_idx {b_val}" if b_val is not None else "no entry"
            return (
                f"class {class_id}: simplify order differs "
                f"(first changed position: {pos}; was {a_str}, now {b_str})"
            )
    # Shouldn't reach here because order_a != order_b implies a divergence,
    # but a length mismatch with identical prefixes would land here.
    return f"class {class_id}: simplify order differs (length: {len(order_a)} -> {len(order_b)})"


def _spill_diff_line(
    class_id: int,
    spills_a: set[int],
    spills_b: set[int],
) -> str | None:
    if spills_a == spills_b:
        return None
    added = sorted(spills_b - spills_a)
    removed = sorted(spills_a - spills_b)
    return (
        f"class {class_id}: spill set differs "
        f"({_fmt_added_removed_ints(added, removed, item_label='ig_idx')})"
    )


def _summarize_input_components(
    class_id: int,
    sec_a: ColorgraphSection,
    sec_b: ColorgraphSection,
    events_a: FunctionEvents | None,
    events_b: FunctionEvents | None,
) -> list[str]:
    """Emit one line per RA input component that differs between A and B.

    Returns an empty list if all four components match. Components that
    are equal across A and B contribute no lines.
    """
    lines: list[str] = []
    edges_a = _interference_edges(sec_a)
    edges_b = _interference_edges(sec_b)
    line = _interference_diff_line(class_id, edges_a, edges_b)
    if line:
        lines.append(line)

    mappings_a = _coalesce_mappings(events_a, class_id)
    mappings_b = _coalesce_mappings(events_b, class_id)
    line = _coalesce_diff_line(class_id, mappings_a, mappings_b)
    if line:
        lines.append(line)

    order_a = _simplify_order(events_a, class_id)
    order_b = _simplify_order(events_b, class_id)
    line = _simplify_order_diff_line(class_id, order_a, order_b)
    if line:
        lines.append(line)

    spills_a = _spill_set(events_a, class_id)
    spills_b = _spill_set(events_b, class_id)
    line = _spill_diff_line(class_id, spills_a, spills_b)
    if line:
        lines.append(line)

    return lines


def _classify_ra(events_a: FunctionEvents | None, events_b: FunctionEvents | None) -> RADiff | None:
    class_ids = sorted({
        section.class_id
        for events in (events_a, events_b)
        if events is not None
        for section in events.colorgraph_sections
    })
    input_changes: list[str] = []
    output_changes: list[str] = []

    for class_id in class_ids:
        sec_a = _section_by_class(events_a, class_id)
        sec_b = _section_by_class(events_b, class_id)
        if sec_a is None or sec_b is None:
            input_changes.append(f"class {class_id}: colorgraph section missing on one side")
            continue
        input_changes.extend(_summarize_input_components(
            class_id, sec_a, sec_b, events_a, events_b,
        ))
        output_a = _ra_output_signature(sec_a)
        output_b = _ra_output_signature(sec_b)
        output_changes.extend(_summarize_tuple_diff(output_a, output_b, f"class {class_id}: coloring output"))

    if not input_changes and not output_changes:
        return None
    classification = "input-derived" if input_changes else "intrinsic"
    return RADiff(
        classification=classification,
        input_changes=input_changes,
        output_changes=output_changes,
    )


def _heuristic_causes(diff_lines: list[str]) -> list[str]:
    joined = "\n".join(diff_lines)
    causes: list[str] = []
    if "divw" in joined and "mulhwu" in joined:
        causes.append("Heuristic cause: signed divide vs unsigned magic-multiply shape; check s32/u32 typing near the divided value.")
    if "srawi" in joined and "srwi" in joined:
        causes.append("Heuristic cause: arithmetic vs logical shift; check signedness of the shifted value.")
    if "volatile" in joined:
        causes.append("Heuristic cause: volatile source shape can block optimization and change live ranges.")
    return causes


def _compare_inspect_snapshots(
    snapshots_a: list[InspectSnapshot],
    snapshots_b: list[InspectSnapshot],
    *,
    label_a: str,
    label_b: str,
) -> list[PassDiff]:
    out: list[PassDiff] = []
    max_len = max(len(snapshots_a), len(snapshots_b))
    for idx in range(max_len):
        snap_a = snapshots_a[idx] if idx < len(snapshots_a) else None
        snap_b = snapshots_b[idx] if idx < len(snapshots_b) else None
        pass_no = idx + 1
        if snap_a is None or snap_b is None or snap_a.name != snap_b.name:
            out.append(PassDiff(
                index=pass_no,
                pass_name=(snap_a.name if snap_a is not None else snap_b.name),
                changed=True,
                kind=DivergenceKind.META,
                summary="inspect snapshot list differs",
            ))
            continue
        changed = snap_a.text != snap_b.text
        diff_lines = _unified_diff(snap_a.text, snap_b.text, label_a, label_b) if changed else []
        out.append(PassDiff(
            index=pass_no,
            pass_name=snap_a.name,
            changed=changed,
            kind=DivergenceKind.TEXT if changed else None,
            summary="text differs" if changed else "",
            diff_lines=diff_lines,
            heuristic_causes=_heuristic_causes(diff_lines) if changed else [],
        ))
    return out


def _event_for_function(
    text: str,
    function: str,
    override_events: Iterable[FunctionEvents] | None,
) -> FunctionEvents | None:
    events = list(override_events) if override_events is not None else parse_hook_events(text)
    return find_event_function(events, function)


def compare_function_dumps(
    text_a: str,
    text_b: str,
    *,
    function: str,
    label_a: str = "A",
    label_b: str = "B",
    events_a: Iterable[FunctionEvents] | None = None,
    events_b: Iterable[FunctionEvents] | None = None,
    inspect_text_a: str | None = None,
    inspect_text_b: str | None = None,
) -> DiffReport:
    fn_a = _find_function_or_raise(text_a, function, label_a)
    fn_b = _find_function_or_raise(text_b, function, label_b)
    ev_a = _event_for_function(text_a, function, events_a)
    ev_b = _event_for_function(text_b, function, events_b)

    raw: list[PassDiff] = []
    if inspect_text_a is not None and inspect_text_b is not None:
        raw.extend(_compare_inspect_snapshots(
            parse_inspect_snapshots(inspect_text_a, function=function),
            parse_inspect_snapshots(inspect_text_b, function=function),
            label_a=label_a,
            label_b=label_b,
        ))

    base_index = len(raw)
    max_len = max(len(fn_a.passes), len(fn_b.passes))

    for idx in range(max_len):
        pass_a = fn_a.passes[idx] if idx < len(fn_a.passes) else None
        pass_b = fn_b.passes[idx] if idx < len(fn_b.passes) else None
        pass_no = base_index + idx + 1

        if pass_a is None or pass_b is None or pass_a.name != pass_b.name:
            name = pass_a.name if pass_a is not None else pass_b.name
            pd = PassDiff(
                index=pass_no,
                pass_name=name or "<missing>",
                changed=True,
                kind=DivergenceKind.META,
                summary="pass list differs",
            )
        elif pass_a.name == "AFTER REGISTER COLORING":
            ra = _classify_ra(ev_a, ev_b)
            text_a_pass = _format_pass_snapshot(pass_a)
            text_b_pass = _format_pass_snapshot(pass_b)
            text_changed = text_a_pass != text_b_pass
            if ra is None and not text_changed:
                pd = PassDiff(index=pass_no, pass_name=pass_a.name, changed=False)
            else:
                kind = (
                    DivergenceKind.RA_INPUT_DERIVED
                    if ra is not None and ra.classification == "input-derived"
                    else DivergenceKind.RA_INTRINSIC
                    if ra is not None
                    else DivergenceKind.TEXT
                )
                summary = (
                    f"register allocation {ra.classification}"
                    if ra is not None
                    else "text differs"
                )
                diff_lines = _unified_diff(text_a_pass, text_b_pass, label_a, label_b) if text_changed else []
                pd = PassDiff(
                    index=pass_no,
                    pass_name=pass_a.name,
                    changed=True,
                    kind=kind,
                    summary=summary,
                    diff_lines=diff_lines,
                    heuristic_causes=_heuristic_causes(diff_lines) if diff_lines else [],
                    ra=ra,
                )
        else:
            snap_a = _format_pass_snapshot(pass_a)
            snap_b = _format_pass_snapshot(pass_b)
            changed = snap_a != snap_b
            diff_lines = _unified_diff(snap_a, snap_b, label_a, label_b) if changed else []
            pd = PassDiff(
                index=pass_no,
                pass_name=pass_a.name,
                changed=changed,
                kind=DivergenceKind.TEXT if changed else None,
                summary="text differs" if changed else "",
                diff_lines=diff_lines,
                heuristic_causes=_heuristic_causes(diff_lines) if diff_lines else [],
            )
        raw.append(pd)

    # Apply cascade tracking across the unified list (inspect snapshots then
    # pcdump passes). The first changed PassDiff is the earliest; every
    # downstream changed PassDiff is marked as cascading from it.
    earliest: PassDiff | None = None
    earliest_index: int | None = None
    out: list[PassDiff] = []
    for pd in raw:
        if pd.changed and earliest is None:
            earliest = pd
            earliest_index = pd.index
            out.append(pd)
        elif pd.changed and earliest_index is not None:
            out.append(PassDiff(
                index=pd.index,
                pass_name=pd.pass_name,
                changed=pd.changed,
                kind=pd.kind,
                summary=pd.summary,
                diff_lines=pd.diff_lines,
                heuristic_causes=pd.heuristic_causes,
                ra=pd.ra,
                cascade_from=earliest_index,
            ))
        else:
            out.append(pd)

    return DiffReport(
        function=function,
        label_a=label_a,
        label_b=label_b,
        passes=out,
        earliest=earliest,
    )


def render_text_report(report: DiffReport) -> str:
    lines: list[str] = [f"Function: {report.function}", f"A: {report.label_a}", f"B: {report.label_b}", ""]
    if report.earliest is None:
        lines.append("NO DIVERGENCE")
    else:
        has_cascade = any(pd.cascade_from is not None for pd in report.passes)
        header = (
            f"EARLIEST DIVERGENCE: {report.earliest.pass_name} "
            f"(pass {report.earliest.index} of {len(report.passes)}"
        )
        if has_cascade:
            header += f"; later divergences cascade from pass {report.earliest.index}"
        header += ")"
        lines.append(header)
        lines.append("")
        lines.extend(_render_lowering_summary(report))
    lines.append("")

    for pd in report.passes:
        if not pd.changed:
            lines.append(f"Pass {pd.index}: {pd.pass_name}")
            lines.append("  OK Identical")
            continue
        if pd.cascade_from is not None:
            tag = f"DIVERGENCE (cascade from pass {pd.cascade_from})"
        elif pd.kind == DivergenceKind.RA_INTRINSIC:
            tag = "DIVERGENCE (intrinsic)"
        elif pd.kind == DivergenceKind.RA_INPUT_DERIVED:
            tag = "DIVERGENCE (input-derived)"
        else:
            tag = "DIVERGENCE (earliest)"
        lines.append(f"Pass {pd.index}: {pd.pass_name}")
        lines.append(f"  {tag}: {pd.summary}")
        if pd.ra is not None:
            # Cap at 32 lines for input_changes (~8 register classes worth
            # of 4 per-component lines). Per-component helpers in
            # _summarize_input_components already bound each component's
            # detail at 6 entries + tail, so runaway is not possible —
            # the renderer's job is to surface what those helpers trimmed.
            # Realistic MWCC pcdumps usually have 2 classes (GPR + FPR),
            # so 32 leaves comfortable headroom.
            for item in pd.ra.input_changes[:32]:
                lines.append(f"  input: {item}")
            # Slice at 9 (not 8) so the "...and N more" tail emitted by
            # _summarize_tuple_diff for over-cap coloring-output diffs still
            # reaches the rendered report.
            for item in pd.ra.output_changes[:9]:
                lines.append(f"  output: {item}")
        for cause in pd.heuristic_causes:
            lines.append(f"  {cause}")
        for diff_line in pd.diff_lines[:16]:
            lines.append(f"  {diff_line}")
    return "\n".join(lines)


def _render_lowering_summary(report: DiffReport) -> list[str]:
    earliest = report.earliest
    if earliest is None:
        return []

    stage, meaning = _classify_lowering_stage(earliest)
    cascades = sum(1 for pd in report.passes if pd.cascade_from == earliest.index)
    lines = [
        "LOWERING SUMMARY",
        f"  earliest stage: {stage}",
        f"  meaning: {meaning}",
    ]
    if cascades:
        lines.append(
            f"  downstream: {cascades} later stage(s) differ after this point"
        )
    if earliest.ra is not None:
        if earliest.ra.input_changes:
            lines.append("  allocator input terms:")
            for item in earliest.ra.input_changes[:4]:
                lines.append(f"    - {item}")
        elif earliest.ra.output_changes:
            lines.append(
                "  allocator output terms: coloring changed with identical "
                "summarized inputs"
            )
    return lines


def _classify_lowering_stage(pass_diff: PassDiff) -> tuple[str, str]:
    name = pass_diff.pass_name.upper()
    if name.startswith("FRONTEND:"):
        return (
            "front-end source IR",
            "source statements/ENodes differ before backend PCode exists",
        )
    if name.startswith("MID-END:"):
        return (
            "front-end/mid-end optimized IR",
            "inspector optimized IR differs before backend PCode emission",
        )
    if pass_diff.kind == DivergenceKind.RA_INPUT_DERIVED:
        return (
            "register-allocation input",
            "allocator inputs changed: interference, coalesce, simplify order, or spill markers differ",
        )
    if pass_diff.kind == DivergenceKind.RA_INTRINSIC:
        return (
            "register-allocation decision",
            "allocator coloring output changed without a summarized input signature change",
        )
    if "BEFORE REGISTER COLORING" in name:
        return (
            "backend PCode before register coloring",
            "generated PCode differs before allocator coloring",
        )
    if "AFTER REGISTER COLORING" in name:
        return (
            "backend PCode after register coloring",
            "colored PCode differs after allocator decisions",
        )
    if "SCHEDUL" in name or "FINAL CODE" in name:
        return (
            "final scheduling/code emission",
            "scheduled final instruction stream differs",
        )
    return (
        "backend PCode pass",
        "backend PCode pass text or pass list differs",
    )
