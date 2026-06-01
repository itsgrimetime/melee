"""Lifetime/layout pressure attribution for source-shape probes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .colorgraph_parser import find_function, parse_hook_events
from .parser import Function, Pass, parse_pcdump
from .simplify_search import baseline_signature
from .virtual_attribution import explain_virtuals


@dataclass(frozen=True)
class TargetPairState:
    virtual: int
    other_virtual: int
    colorgraph_interference: bool
    live_overlap: bool
    same_assigned_reg: bool | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "virtual": self.virtual,
            "other_virtual": self.other_virtual,
            "colorgraph_interference": self.colorgraph_interference,
            "live_overlap": self.live_overlap,
            "same_assigned_reg": self.same_assigned_reg,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PairDelta:
    before: TargetPairState
    after: TargetPairState

    @property
    def improved(self) -> bool:
        return (
            self.before.colorgraph_interference
            and not self.after.colorgraph_interference
        ) or (
            self.before.live_overlap
            and not self.after.live_overlap
        )

    def to_dict(self) -> dict:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "improved": self.improved,
        }


@dataclass(frozen=True)
class PressureSignature:
    frame_size: int | None
    saved_regs: tuple[str, ...]
    spill_set: tuple[int, ...]
    interference_edges: tuple[tuple[int, int], ...]
    coalesce_mappings: tuple[tuple[int, int], ...]
    target_pairs: tuple[TargetPairState, ...]

    def to_dict(self) -> dict:
        return {
            "frame_size": self.frame_size,
            "saved_regs": list(self.saved_regs),
            "spill_set": list(self.spill_set),
            "interference_edges": [list(edge) for edge in self.interference_edges],
            "coalesce_mappings": [list(pair) for pair in self.coalesce_mappings],
            "target_pairs": [pair.to_dict() for pair in self.target_pairs],
        }


@dataclass(frozen=True)
class PressureDelta:
    frame_before: int | None
    frame_after: int | None
    frame_delta: int | None
    saved_added: tuple[str, ...]
    saved_removed: tuple[str, ...]
    spill_added: tuple[int, ...]
    spill_removed: tuple[int, ...]
    interference_added: tuple[tuple[int, int], ...]
    interference_removed: tuple[tuple[int, int], ...]
    coalesce_added: tuple[tuple[int, int], ...]
    coalesce_removed: tuple[tuple[int, int], ...]
    target_pairs: tuple[PairDelta, ...]

    def to_dict(self) -> dict:
        return {
            "frame_before": self.frame_before,
            "frame_after": self.frame_after,
            "frame_delta": self.frame_delta,
            "saved_added": list(self.saved_added),
            "saved_removed": list(self.saved_removed),
            "spill_added": list(self.spill_added),
            "spill_removed": list(self.spill_removed),
            "interference_added": [
                list(edge) for edge in self.interference_added
            ],
            "interference_removed": [
                list(edge) for edge in self.interference_removed
            ],
            "coalesce_added": [list(pair) for pair in self.coalesce_added],
            "coalesce_removed": [list(pair) for pair in self.coalesce_removed],
            "target_pairs": [pair.to_dict() for pair in self.target_pairs],
        }


@dataclass(frozen=True)
class LifetimeLayoutProbe:
    label: str
    operator: str
    description: str
    source_text: str
    provenance: dict | None = None

    def to_dict(self, *, include_source: bool = False) -> dict:
        data = {
            "label": self.label,
            "operator": self.operator,
            "description": self.description,
        }
        if self.provenance is not None:
            data["provenance"] = self.provenance
        if include_source:
            data["source_text"] = self.source_text
        return data


_FRAME_RE = re.compile(r"\br1\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)")
_STMW_RE = re.compile(r"\br(\d+)\s*,")
_STW_RE = re.compile(r"\br(\d+)\s*,\s*[-+]?(?:0x[0-9A-Fa-f]+|\d+)\s*\(\s*r1\s*\)")
_STFD_RE = re.compile(r"\bf(\d+)\s*,\s*[-+]?(?:0x[0-9A-Fa-f]+|\d+)\s*\(\s*r1\s*\)")
_LOCAL_DECL_RE = re.compile(
    r"^[ \t]*(?:const\s+|volatile\s+)*"
    r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
    r"(?:\s*\*)*\s+([A-Za-z_]\w*)\s*(?:=\s*[^;]*)?;\s*$"
)
_DECL_LINE_RE = re.compile(
    r"^([ \t]*)(int|s32|u32|float|double|[A-Za-z_]\w+(?:\s*\*)?)"
    r"\s+([A-Za-z_]\w*)\s*;\n?$"
)
_MEMBER_EXPR_RE = (
    r"[A-Za-z_]\w*\s*(?:->|\.)\s*[A-Za-z_]\w*"
)
_DIFF_EXPR_RE = (
    rf"{_MEMBER_EXPR_RE}\s*-\s*{_MEMBER_EXPR_RE}"
)


def pressure_signature_from_pcdump(
    pcdump_text: str,
    function: str,
    *,
    pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
    class_id: int = 0,
) -> PressureSignature:
    """Extract pressure-relevant allocator/prologue facts for one function."""
    events = find_function(parse_hook_events(pcdump_text), function)
    parsed = parse_pcdump(pcdump_text, function=function)
    if events is None and not parsed:
        raise ValueError(f"{function} not found in pcdump")
    if events is not None:
        sig = baseline_signature(events, class_id=class_id)
        spill_set = tuple(sorted(_spilled_markers(events)))
        interference_edges = tuple(sorted(sig.interference_edges))
        coalesce_mappings = tuple(sorted(sig.coalesce_mappings))
    else:
        spill_set = ()
        interference_edges = ()
        coalesce_mappings = ()

    fn = parsed[0] if parsed else None
    frame_size, saved_regs = _frame_and_saved_regs(fn)
    pair_states = _target_pair_states(pcdump_text, function, pairs)
    return PressureSignature(
        frame_size=frame_size,
        saved_regs=saved_regs,
        spill_set=spill_set,
        interference_edges=interference_edges,
        coalesce_mappings=coalesce_mappings,
        target_pairs=pair_states,
    )


def _spilled_markers(events) -> set[int]:
    """All simplifygraph SPILLED markers, matching inspect/stuck reporting."""
    spilled: set[int] = set()
    for section in events.simplify_sections:
        for entry in section.entries:
            if entry.spilled and entry.ig_idx >= 0:
                spilled.add(entry.ig_idx)
    return spilled


def compare_pressure_signatures(
    baseline: PressureSignature,
    candidate: PressureSignature,
) -> PressureDelta:
    frame_delta = None
    if baseline.frame_size is not None and candidate.frame_size is not None:
        frame_delta = candidate.frame_size - baseline.frame_size

    saved_before = set(baseline.saved_regs)
    saved_after = set(candidate.saved_regs)
    spill_before = set(baseline.spill_set)
    spill_after = set(candidate.spill_set)
    ig_before = set(baseline.interference_edges)
    ig_after = set(candidate.interference_edges)
    co_before = set(baseline.coalesce_mappings)
    co_after = set(candidate.coalesce_mappings)
    pair_after = {
        (pair.virtual, pair.other_virtual): pair
        for pair in candidate.target_pairs
    }
    pair_deltas = []
    for before in baseline.target_pairs:
        after = pair_after.get((before.virtual, before.other_virtual))
        if after is None:
            continue
        pair_deltas.append(PairDelta(before=before, after=after))
    return PressureDelta(
        frame_before=baseline.frame_size,
        frame_after=candidate.frame_size,
        frame_delta=frame_delta,
        saved_added=tuple(sorted(saved_after - saved_before)),
        saved_removed=tuple(sorted(saved_before - saved_after)),
        spill_added=tuple(sorted(spill_after - spill_before)),
        spill_removed=tuple(sorted(spill_before - spill_after)),
        interference_added=tuple(sorted(ig_after - ig_before)),
        interference_removed=tuple(sorted(ig_before - ig_after)),
        coalesce_added=tuple(sorted(co_after - co_before)),
        coalesce_removed=tuple(sorted(co_before - co_after)),
        target_pairs=tuple(pair_deltas),
    )


def render_pressure_delta(
    label: str,
    operator: str,
    delta: PressureDelta,
) -> str:
    lines = [f"- {label} [{operator}]"]
    if delta.frame_delta is None:
        lines.append("  frame: unchanged/unknown")
    else:
        sign = "+" if delta.frame_delta > 0 else ""
        lines.append(
            f"  frame: {delta.frame_before} -> {delta.frame_after} "
            f"({sign}{delta.frame_delta})"
        )
    lines.append(
        "  saved: "
        f"+{_fmt_regs(delta.saved_added)} -{_fmt_regs(delta.saved_removed)}"
    )
    lines.append(
        "  spill: "
        f"+{_fmt_ints(delta.spill_added)} -{_fmt_ints(delta.spill_removed)}"
    )
    lines.append(
        "  interference: "
        f"+{len(delta.interference_added)} -{len(delta.interference_removed)}"
    )
    lines.append(
        "  coalesce: "
        f"+{len(delta.coalesce_added)} -{len(delta.coalesce_removed)}"
    )
    for pair in delta.target_pairs:
        before = "yes" if pair.before.colorgraph_interference else "no"
        after = "yes" if pair.after.colorgraph_interference else "no"
        marker = " improved" if pair.improved else ""
        lines.append(
            f"  target r{pair.before.virtual}/r{pair.before.other_virtual}: "
            f"interference {before}->{after}; "
            f"live {pair.before.live_overlap}->{pair.after.live_overlap}"
            f"{marker}"
        )
    return "\n".join(lines)


def generate_lifetime_layout_probes(
    source_text: str,
    function: str,
    *,
    frame_reservation_bytes: int | None = None,
    max_probes: int = 12,
) -> list[LifetimeLayoutProbe]:
    """Generate conservative source-shape probes for pressure exploration.

    These are intentionally simple, mechanical variants. The command that
    consumes them compiles and scores the pressure effect; this generator only
    provides representative actuators for each operator family.
    """
    span = _find_function_body_span(source_text, function)
    if span is None:
        return []
    body_start, body_end = span
    body = source_text[body_start:body_end]
    probes: list[LifetimeLayoutProbe] = []

    if frame_reservation_bytes is not None and frame_reservation_bytes > 0:
        _append_probe(
            probes,
            _probe_frame_reservation_pad_stack(
                source_text,
                body,
                body_start,
                frame_reservation_bytes,
            ),
        )
    for probe in _probe_call_return_compare_chain(
        source_text,
        body,
        body_start,
        body_end,
        function,
    ):
        _append_probe(probes, probe)
    for probe in _probe_expression_shape(source_text, body, body_start, function):
        _append_probe(probes, probe)
    for probe in _probe_declaration_order(source_text, body, body_start, function):
        _append_probe(probes, probe)
    _append_probe(
        probes,
        _probe_temp_introduction(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_temp_removal(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_type_width(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_declaration_use_distance(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_boolean_guard_switch(source_text, body, body_start, body_end, function),
    )
    _append_probe(
        probes,
        _probe_early_guard_return(source_text, body, body_start, body_end, function),
    )
    _append_probe(
        probes,
        _probe_block_scope(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_loop_init(source_text, body, body_start, function),
    )
    _append_probe(
        probes,
        _probe_condition_nesting(source_text, body, body_start, body_end, function),
    )
    _append_probe(
        probes,
        _probe_call_arg_temp(source_text, body, body_start, function),
    )
    return probes[:max_probes]


def _target_pair_states(
    pcdump_text: str,
    function: str,
    pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...],
) -> tuple[TargetPairState, ...]:
    if not pairs:
        return ()
    report = explain_virtuals(
        pcdump_text,
        function,
        virtuals=[],
        pairs=pairs,
    )
    return tuple(
        TargetPairState(
            virtual=pair.virtual,
            other_virtual=pair.other_virtual,
            colorgraph_interference=pair.colorgraph_interference,
            live_overlap=pair.live_overlap,
            same_assigned_reg=pair.same_assigned_reg,
            reason=pair.reason,
        )
        for pair in report.pair_interferences
    )


def _frame_and_saved_regs(fn: Function | None) -> tuple[int | None, tuple[str, ...]]:
    if fn is None:
        return None, ()
    selected = _select_final_pass(fn)
    if selected is None:
        return None, ()
    frame_size: int | None = None
    saved: set[str] = set()
    instructions = [
        instr
        for block in selected.blocks[:2]
        for instr in block.instructions[:32]
    ]
    for instr in instructions:
        if instr.opcode == "stwu" and frame_size is None:
            match = _FRAME_RE.search(instr.operands)
            if match is not None:
                frame_size = abs(int(match.group(1), 0))
        if instr.opcode == "stmw":
            match = _STMW_RE.search(instr.operands)
            if match is not None:
                start = int(match.group(1))
                if 13 <= start <= 31:
                    saved.update(f"r{reg}" for reg in range(start, 32))
        elif instr.opcode == "stw":
            match = _STW_RE.search(instr.operands)
            if match is not None:
                reg = int(match.group(1))
                if 13 <= reg <= 31:
                    saved.add(f"r{reg}")
        elif instr.opcode == "stfd":
            match = _STFD_RE.search(instr.operands)
            if match is not None:
                reg = int(match.group(1))
                if 14 <= reg <= 31:
                    saved.add(f"f{reg}")
    return frame_size, tuple(sorted(saved, key=_reg_sort_key))


def _select_final_pass(fn: Function) -> Pass | None:
    preferred = (
        "FINAL CODE AFTER INSTRUCTION SCHEDULING",
        "AFTER PEEPHOLE OPTIMIZATION",
        "AFTER MERGING EPILOGUE, PROLOGUE",
        "AFTER GENERATING EPILOGUE, PROLOGUE",
    )
    by_name = {p.name: p for p in fn.passes}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return fn.passes[-1] if fn.passes else None


def _reg_sort_key(reg: str) -> tuple[int, int]:
    return (0 if reg.startswith("r") else 1, int(reg[1:]))


def _fmt_regs(regs: tuple[str, ...]) -> str:
    return ",".join(regs) if regs else "-"


def _fmt_ints(values: tuple[int, ...]) -> str:
    return ",".join(str(v) for v in values) if values else "-"


def _append_probe(
    probes: list[LifetimeLayoutProbe],
    probe: LifetimeLayoutProbe | None,
) -> None:
    if probe is None:
        return
    if probe.source_text in {existing.source_text for existing in probes}:
        return
    probes.append(probe)


def _find_function_body_span(source: str, function: str) -> tuple[int, int] | None:
    for match in re.finditer(rf"\b{re.escape(function)}\s*\(", source):
        open_paren = source.find("(", match.start(), match.end())
        if open_paren < 0:
            continue
        close_paren = _find_matching_paren(source, open_paren)
        if close_paren is None:
            continue
        cursor = close_paren + 1
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        if cursor >= len(source) or source[cursor] != "{":
            continue
        depth = 0
        for idx in range(cursor, len(source)):
            char = source[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return cursor + 1, idx
    return None


def _replace_body_slice(
    source: str,
    body_start: int,
    rel_start: int,
    rel_end: int,
    replacement: str,
) -> str:
    start = body_start + rel_start
    end = body_start + rel_end
    return source[:start] + replacement + source[end:]


def _probe_temp_introduction(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)([A-Za-z_]\w*)\s*=\s*([^;\n]*(?:\+|-|\*|/)[^;\n]*);",
        body,
    )
    declaration = False
    if match is None:
        match = re.search(
            r"(?m)^([ \t]*)((?:s32|u32|int|float|double)\s+"
            r"([A-Za-z_]\w*))\s*=\s*([^;\n]*(?:\+|-|\*|/)[^;\n]*);",
            body,
        )
        if match is None:
            return None
        declaration = True
    temp = "ll_probe_temp_0"
    if declaration:
        indent, decl_lhs, lhs, expr = match.groups()
        replacement = (
            f"{indent}{decl_lhs};\n"
            f"{indent}int {temp} = {expr.strip()};\n"
            f"{indent}{lhs} = {temp};"
        )
    else:
        indent, lhs, expr = match.groups()
        replacement = (
            f"{indent}int {temp} = {expr.strip()};\n"
            f"{indent}{lhs} = {temp};"
        )
    return LifetimeLayoutProbe(
        label="temp-introduction-0",
        operator="temp-introduction",
        description="Introduce a named temp for one compound assignment RHS.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), match.end(), replacement
        ),
    )


def _probe_temp_removal(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)(?:s32|u32|int|float|double|[A-Za-z_]\w+\s*\*)\s+"
        r"([A-Za-z_]\w*)\s*=\s*([^;\n]+);\n"
        r"((?:[ \t]*(?:s32|u32|int|float|double|[A-Za-z_]\w+\s*\*)\s+"
        r"[A-Za-z_]\w*(?:\s*=\s*[^;\n]+)?;\n){0,2})"
        r"([ \t]*)([A-Za-z_]\w*)\s*=\s*\2\s*;",
        body,
    )
    if match is None:
        return None
    _indent, temp, expr, middle, assign_indent, lhs = match.groups()
    replacement = f"{middle}{assign_indent}{lhs} = {expr.strip()};"
    return LifetimeLayoutProbe(
        label="temp-removal-0",
        operator="temp-removal",
        description=f"Inline one-use temp `{temp}` into the following assignment.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), match.end(), replacement
        ),
    )


def _probe_type_width(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    replacements = {
        "s32": "int",
        "int": "s32",
        "u8": "u32",
        "s8": "s32",
        "u16": "u32",
        "s16": "s32",
        "u32": "u16",
    }
    match = re.search(
        r"(?m)^([ \t]*)(s32|u32|int|u16|s16|u8|s8)\s+([A-Za-z_]\w*)\s*(?=[=;])",
        body,
    )
    if match is None:
        return None
    old_type = match.group(2)
    new_type = replacements[old_type]
    replacement = f"{match.group(1)}{new_type} {match.group(3)}"
    return LifetimeLayoutProbe(
        label="type-width-0",
        operator="type-width",
        description=f"Change local `{match.group(3)}` type {old_type} -> {new_type}.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), match.end(), replacement
        ),
    )


def _probe_declaration_use_distance(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    for match in re.finditer(
        r"(?m)^([ \t]*)(?:int|s32|u32|float|double|[A-Za-z_]\w+\s*\*)\s+"
        r"([A-Za-z_]\w*)\s*;\n",
        body,
    ):
        indent, name = match.groups()
        use_start = _first_later_line_with_identifier(body, match.end(), name)
        if use_start is None:
            continue
        use_line_end = body.find("\n", use_start)
        if use_line_end < 0:
            use_line_end = len(body)
        use_line = body[use_start:use_line_end]
        if re.match(rf"\s*for\s*\(\s*{re.escape(name)}\s*=", use_line):
            continue
        between = body[match.end():use_start]
        if not between.strip():
            continue
        paragraph = body[use_start:_paragraph_end(body, use_start)]
        if _block_crosses_shallower_else(paragraph, use_line):
            continue
        use_end = _declaration_use_region_end(body, use_start, name)
        if use_end is None:
            continue
        use_block = body[use_start:use_end]
        decl_text = match.group(0).strip()
        wrapped = (
            f"{indent}{{\n"
            f"{indent}    {decl_text}\n"
            f"{_indent_block_lines(use_block, indent)}"
            f"{indent}}}\n"
        )
        moved_body = body[:match.start()] + body[match.end():use_start]
        moved_body += wrapped
        moved_body += body[use_end:]
        return LifetimeLayoutProbe(
            label="declaration-use-distance-0",
            operator="declaration-use-distance",
            description=f"Move `{name}` declaration down next to its first use.",
            source_text=(
                source[:body_start] + moved_body + source[body_start + len(body):]
            ),
        )
    return None


def _probe_early_guard_return(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    if re.search(rf"\bvoid\s+{re.escape(function)}\s*\(", source[:body_start]) is None:
        return None
    for match in re.finditer(r"(?m)^([ \t]*)if\s*\(", body):
        indent = match.group(1)
        condition_start = body_start + match.end() - 1
        condition_end = _find_matching_paren(source, condition_start)
        if condition_end is None or condition_end > body_end:
            continue
        open_brace = source.find("{", condition_end, body_end)
        if open_brace < 0:
            continue
        close_brace = _find_matching_brace(source, open_brace)
        if close_brace is None or close_brace > body_end:
            continue
        trailing = source[close_brace + 1:body_end].lstrip()
        if trailing.startswith("else"):
            continue
        condition = source[condition_start + 1:condition_end].strip()
        inner = source[open_brace + 1:close_brace]
        unwrapped = _outdent_block_lines(inner, indent + "    ", indent)
        if unwrapped.startswith("\n"):
            unwrapped = unwrapped[1:]
        replacement = (
            f"{indent}if (!({condition})) {{\n"
            f"{indent}    return;\n"
            f"{indent}}}\n"
            f"{unwrapped}"
        )
        return LifetimeLayoutProbe(
            label="early-guard-return-0",
            operator="early-guard-return",
            description="Invert a top-level guard and unwrap its body after return.",
            source_text=source[:body_start + match.start()]
            + replacement
            + source[close_brace + 1:],
        )
    return None


def _probe_block_scope(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|s32|u32|int|float|double|[A-Za-z_]\w*)"
        r"(?:\s*\*)*\s+[A-Za-z_]\w*(?:\s*=\s*[^;\n]+)?;\n",
        body,
    )
    if match is None:
        return None
    indent = match.group(1)
    names = _leading_local_decl_names(body[match.start():])
    if not names:
        return None
    block_end = _last_line_end_for_identifiers(body, match.start(), names)
    if block_end is None:
        return None
    block_end = max(block_end, match.end())
    block_text = body[match.start():block_end]
    replacement = _wrap_block_text(block_text, indent)
    return LifetimeLayoutProbe(
        label="block-scope-0",
        operator="block-scope",
        description="Tighten one local declaration and following statement into a block.",
        source_text=_replace_body_slice(
            source, body_start, match.start(), block_end, replacement
        ),
    )


def _probe_loop_init(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    decl = re.search(r"(?m)^([ \t]*)(int|s32)\s+([A-Za-z_]\w*)\s*;\n", body)
    if decl is None:
        return None
    indent, typ, var = decl.groups()
    for_match = re.search(
        rf"(?m)^([ \t]*)for\s*\(\s*{re.escape(var)}\s*=",
        body[decl.end():],
    )
    if for_match is None:
        return None
    rel_for_start = decl.end() + for_match.start()
    between = body[decl.end():rel_for_start]
    if re.search(rf"\b{re.escape(var)}\b", between):
        return None
    abs_for_start = body_start + rel_for_start
    abs_for_open = source.find("{", abs_for_start, body_start + len(body))
    if abs_for_open < 0:
        return None
    abs_for_close = _find_matching_brace(source, abs_for_open)
    if abs_for_close is None or abs_for_close > body_start + len(body):
        return None

    decl_abs_start = body_start + decl.start()
    decl_abs_end = body_start + decl.end()
    loop_indent = for_match.group(1)
    loop_text = source[abs_for_start:abs_for_close + 1]
    indented_loop = _indent_block_lines(loop_text, loop_indent)
    if not indented_loop.endswith("\n"):
        indented_loop += "\n"
    replacement = (
        f"{loop_indent}{{\n"
        f"{loop_indent}    {typ} {var};\n"
        f"{indented_loop}"
        f"{loop_indent}}}"
    )
    mutated = (
        source[:decl_abs_start]
        + source[decl_abs_end:abs_for_start]
        + replacement
        + source[abs_for_close + 1:]
    )
    return LifetimeLayoutProbe(
        label="loop-init-0",
        operator="loop-init",
        description=f"Move `{var}` declaration into a tight block around the loop.",
        source_text=mutated,
    )


def _probe_condition_nesting(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    match = re.search(
        r"(?m)^([ \t]*)if\s*\(([^()\n]+)\s*&&\s*([^()\n]+)\)\s*\{",
        body,
    )
    if match is None:
        return None
    absolute_open = body_start + match.end() - 1
    absolute_close = _find_matching_brace(source, absolute_open)
    if absolute_close is None or absolute_close > body_end:
        return None
    indent, left, right = match.groups()
    header = f"{indent}if ({left.strip()}) {{\n{indent}    if ({right.strip()}) {{"
    start = body_start + match.start()
    end = body_start + match.end()
    mutated = source[:start] + header + source[end:absolute_close + 1]
    mutated += f"\n{indent}}}" + source[absolute_close + 1:]
    return LifetimeLayoutProbe(
        label="condition-nesting-0",
        operator="condition-nesting",
        description="Split a conjunctive condition into nested if statements.",
        source_text=mutated,
    )


def _probe_call_arg_temp(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    scoped_types = _scoped_identifier_types(source, body, body_start, function)
    for match in re.finditer(
        r"(?m)^([ \t]*)([A-Za-z_]\w*)\(([^;\n]*)\);",
        body,
    ):
        indent, call, args_text = match.groups()
        args = list(_split_top_level_args(args_text))
        for index, arg in enumerate(args):
            if not _has_tempizable_arithmetic(arg):
                continue
            temp = "ll_probe_arg_0"
            temp_type = _infer_call_arg_temp_type(arg, scoped_types)
            args[index] = temp
            replacement = (
                f"{indent}{{\n"
                f"{indent}    {temp_type} {temp} = {arg.strip()};\n"
                f"{indent}    {call}({', '.join(args)});\n"
                f"{indent}}}"
            )
            return LifetimeLayoutProbe(
                label="call-arg-tempization-0",
                operator="call-argument-tempization",
                description="Hoist one compound call argument into a named temp.",
                source_text=_replace_body_slice(
                    source, body_start, match.start(), match.end(), replacement
                ),
                provenance={
                    "kind": "call-argument-tempization",
                    "call": call,
                    "argument_index": index,
                    "temp_type": temp_type,
                },
            )
    return None


def _probe_frame_reservation_pad_stack(
    source: str,
    body: str,
    body_start: int,
    bytes_: int,
) -> LifetimeLayoutProbe | None:
    existing = re.search(
        r"(?m)^([ \t]*)PAD_STACK\(\s*(0x[0-9A-Fa-f]+|\d+)\s*\);\n?",
        body,
    )
    if existing is not None:
        previous = int(existing.group(2), 0)
        if previous == bytes_:
            return None
        indent = existing.group(1)
        replacement = f"{indent}PAD_STACK({bytes_});\n"
        return LifetimeLayoutProbe(
            label=f"frame-reservation-pad-stack-{bytes_}",
            operator="frame-reservation-pad-stack",
            description=(
                f"Replace existing PAD_STACK({previous}) with PAD_STACK({bytes_}) "
                "to test an implicit no-access frame reservation."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                existing.start(),
                existing.end(),
                replacement,
            ),
            provenance={
                "kind": "frame-reservation-pad-stack",
                "bytes": bytes_,
                "action": "replace",
                "previous_bytes": previous,
            },
        )

    insert_rel, indent = _pad_stack_insert_position(body)
    if insert_rel is None:
        return None
    line = f"{indent}PAD_STACK({bytes_});\n"
    return LifetimeLayoutProbe(
        label=f"frame-reservation-pad-stack-{bytes_}",
        operator="frame-reservation-pad-stack",
        description=(
            f"Insert PAD_STACK({bytes_}) to test an implicit no-access "
            "frame reservation."
        ),
        source_text=(
            source[: body_start + insert_rel]
            + line
            + source[body_start + insert_rel :]
        ),
        provenance={
            "kind": "frame-reservation-pad-stack",
            "bytes": bytes_,
            "action": "insert",
        },
    )


def _pad_stack_insert_position(body: str) -> tuple[int | None, str]:
    cursor = 0
    insert_rel: int | None = None
    indent = "    "
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            if insert_rel is not None:
                break
            cursor += len(line)
            continue
        match = _LOCAL_DECL_RE.match(line)
        if match is not None:
            indent_match = re.match(r"[ \t]*", line)
            indent = "" if indent_match is None else indent_match.group(0)
            insert_rel = cursor + len(line)
            cursor += len(line)
            continue
        if insert_rel is None:
            indent_match = re.match(r"[ \t]*", line)
            indent = "" if indent_match is None else indent_match.group(0)
            insert_rel = cursor
        break
    if insert_rel is None:
        insert_rel = len(body)
    return insert_rel, indent


def _scoped_identifier_types(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> dict[str, str]:
    types: dict[str, str] = {}
    params = _function_param_text(source, function, body_start)
    if params is not None:
        for part in _split_top_level_args(params):
            parsed = _parse_simple_decl(part)
            if parsed is not None:
                name, typ = parsed
                types[name] = typ
    for match in re.finditer(
        r"(?m)^[ \t]*(?P<type>f32|float|double|s32|u32|int)\s+"
        r"(?:\*+\s*)?(?P<name>[A-Za-z_]\w*)\s*(?:[=;,\[])",
        body,
    ):
        types[match.group("name")] = match.group("type")
    return types


def _function_param_text(
    source: str,
    function: str,
    body_start: int,
) -> str | None:
    prefix = source[:body_start]
    matches = list(re.finditer(rf"\b{re.escape(function)}\s*\(", prefix))
    if not matches:
        return None
    open_paren = prefix.find("(", matches[-1].start())
    close_paren = _find_matching_paren(source, open_paren)
    if close_paren is None or close_paren > body_start:
        return None
    return source[open_paren + 1:close_paren]


def _parse_simple_decl(text: str) -> tuple[str, str] | None:
    if "(*" in text:
        return None
    text = re.sub(r"\s+", " ", text.strip())
    match = re.match(
        r"^(?P<type>(?:const\s+|volatile\s+)*(?:f32|float|double|s32|u32|int|"
        r"[A-Za-z_]\w+)(?:\s*\*)*)\s+(?P<name>[A-Za-z_]\w*)$",
        text,
    )
    if match is None:
        return None
    typ = match.group("type").replace("const ", "").replace("volatile ", "").strip()
    return match.group("name"), typ


def _infer_call_arg_temp_type(expr: str, scoped_types: dict[str, str]) -> str:
    names = set(re.findall(r"\b[A-Za-z_]\w*\b", expr))
    referenced_types = {scoped_types[name] for name in names if name in scoped_types}
    if "double" in referenced_types:
        return "double"
    if "f32" in referenced_types:
        return "f32"
    if "float" in referenced_types or re.search(r"\d+\.\d*|\d*\.\d+|\d+\.?f\b", expr):
        return "float"
    return "int"


@dataclass(frozen=True)
class _DeclLine:
    start: int
    end: int
    indent: str
    type_name: str
    name: str
    text: str
    depth: int


def _probe_declaration_order(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    hoist_before, hoist_after = _probe_nested_loop_counter_hoist(
        source,
        body,
        body_start,
        function,
    )
    if hoist_before is not None:
        probes.append(hoist_before)
    adjacent = _probe_adjacent_decl_swap(source, body, body_start, function)
    if adjacent is not None:
        probes.append(adjacent)
    loop_type = _probe_loop_counter_type(source, body, body_start, function)
    if loop_type is not None:
        probes.append(loop_type)
    if hoist_after is not None:
        probes.append(hoist_after)
    return probes


def _probe_expression_shape(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    probes: list[LifetimeLayoutProbe] = []
    assignment = _probe_assignment_expression_cse_removal(
        source,
        body,
        body_start,
        function,
    )
    if assignment is not None:
        probes.append(assignment)
    distance = _probe_distance_component_temps(source, body, body_start, function)
    if distance is not None:
        probes.append(distance)
    abs_discriminator = _probe_abs_branch_discriminator_split(
        source,
        body,
        body_start,
        function,
    )
    if abs_discriminator is not None:
        probes.append(abs_discriminator)
    return probes


def _iter_decl_lines(body: str) -> list[_DeclLine]:
    decls: list[_DeclLine] = []
    depth = 0
    cursor = 0
    for line in body.splitlines(keepends=True):
        line_depth = depth
        match = _DECL_LINE_RE.match(line)
        if match is not None:
            indent, type_name, name = match.groups()
            decls.append(
                _DeclLine(
                    start=cursor,
                    end=cursor + len(line),
                    indent=indent,
                    type_name=type_name.replace(" ", ""),
                    name=name,
                    text=line,
                    depth=line_depth,
                )
            )
        for char in line:
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(0, depth - 1)
        cursor += len(line)
    return decls


def _probe_adjacent_decl_swap(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    top_decls = [decl for decl in _iter_decl_lines(body) if decl.depth == 0]
    for left, right in zip(top_decls, top_decls[1:]):
        if left.end != right.start or left.indent != right.indent:
            continue
        mutated = _replace_body_slice(
            source,
            body_start,
            left.start,
            right.end,
            right.text + left.text,
        )
        return LifetimeLayoutProbe(
            label="adjacent-decl-swap-0",
            operator="declaration-order",
            description=(
                f"Swap adjacent function-scope locals `{left.name}` and "
                f"`{right.name}` to test allocator role order."
            ),
            source_text=mutated,
            provenance={
                "kind": "adjacent-decl-swap",
                "first": left.name,
                "second": right.name,
            },
        )
    return None


def _probe_loop_counter_type(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    decls = _iter_decl_lines(body)
    first_width_decl = next(
        (decl for decl in decls if decl.type_name in {"int", "s32", "u32"}),
        None,
    )
    for decl in decls:
        if decl.type_name not in {"int", "s32"}:
            continue
        if first_width_decl == decl:
            continue
        if _find_loop_using_counter(body, decl.end, decl.name) is None:
            continue
        new_type = "int" if decl.type_name == "s32" else "s32"
        replacement = f"{decl.indent}{new_type} {decl.name};\n"
        return LifetimeLayoutProbe(
            label="loop-counter-type-0",
            operator="loop-counter-type",
            description=(
                f"Change loop counter `{decl.name}` type "
                f"{decl.type_name} -> {new_type}."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                decl.start,
                decl.end,
                replacement,
            ),
            provenance={
                "kind": "loop-counter-type",
                "counter": decl.name,
                "from_type": decl.type_name,
                "to_type": new_type,
            },
        )
    return None


def _probe_nested_loop_counter_hoist(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> tuple[LifetimeLayoutProbe | None, LifetimeLayoutProbe | None]:
    decls = _iter_decl_lines(body)
    top_decls = [decl for decl in decls if decl.depth == 0]
    if not top_decls:
        return None, None

    for decl in decls:
        if decl.depth == 0 or decl.type_name not in {"int", "s32"}:
            continue
        loop_start = _find_loop_using_counter(body, decl.end, decl.name)
        if loop_start is None:
            continue
        between = body[decl.end:loop_start]
        if between.strip():
            continue

        insert_type = "int"
        insert_indent = top_decls[0].indent
        insert_text = f"{insert_indent}{insert_type} {decl.name};\n"

        before_target = _preferred_loop_counter_insert_target(top_decls)
        before_source = _move_decl_to_body_offset(
            source,
            body,
            body_start,
            decl,
            before_target.start,
            insert_text,
        )
        before_probe = LifetimeLayoutProbe(
            label="loop-counter-hoist-before-0",
            operator="loop-counter-hoist",
            description=(
                f"Hoist nested loop counter `{decl.name}` to function scope "
                f"before `{before_target.name}` as int."
            ),
            source_text=before_source,
            provenance={
                "kind": "loop-counter-hoist",
                "counter": decl.name,
                "from_type": decl.type_name,
                "to_type": insert_type,
                "placement": f"before:{before_target.name}",
            },
        )

        after_probe: LifetimeLayoutProbe | None = None
        if len(top_decls) > 1:
            after_source = _move_decl_to_body_offset(
                source,
                body,
                body_start,
                decl,
                before_target.end,
                insert_text,
            )
            after_probe = LifetimeLayoutProbe(
                label="loop-counter-hoist-after-0",
                operator="loop-counter-hoist",
                description=(
                    f"Hoist nested loop counter `{decl.name}` immediately "
                    f"after `{before_target.name}` as int."
                ),
                source_text=after_source,
                provenance={
                    "kind": "loop-counter-hoist",
                    "counter": decl.name,
                    "from_type": decl.type_name,
                    "to_type": insert_type,
                    "placement": f"after:{before_target.name}",
                },
            )
        return before_probe, after_probe

    return None, None


def _preferred_loop_counter_insert_target(decls: list[_DeclLine]) -> _DeclLine:
    count_decl = next((decl for decl in decls if decl.name == "count"), None)
    return count_decl or decls[0]


def _move_decl_to_body_offset(
    source: str,
    body: str,
    body_start: int,
    decl: _DeclLine,
    insert_offset: int,
    insert_text: str,
) -> str:
    body_without_decl = body[:decl.start] + body[decl.end:]
    adjusted_insert = insert_offset
    if insert_offset > decl.start:
        adjusted_insert -= decl.end - decl.start
    moved_body = (
        body_without_decl[:adjusted_insert]
        + insert_text
        + body_without_decl[adjusted_insert:]
    )
    return source[:body_start] + moved_body + source[body_start + len(body):]


def _find_loop_using_counter(body: str, start: int, name: str) -> int | None:
    match = re.search(
        rf"(?m)^([ \t]*)for\s*\(\s*{re.escape(name)}\s*=",
        body[start:],
    )
    if match is None:
        return None
    return start + match.start()


def _probe_assignment_expression_cse_removal(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    assign_re = re.compile(
        rf"\(\s*(?P<temp>[A-Za-z_]\w*)\s*=\s*(?P<expr>{_MEMBER_EXPR_RE})\s*\)"
    )
    for match in assign_re.finditer(body):
        temp = match.group("temp")
        expr = _normalize_inline_expr(match.group("expr"))
        stmt_start, stmt_end = _statement_bounds_around(body, match.start())
        if stmt_start is None or stmt_end is None:
            continue
        statement = body[stmt_start:stmt_end]
        rel_start = match.start() - stmt_start
        rel_end = match.end() - stmt_start
        rewritten = statement[:rel_start] + expr + statement[rel_end:]
        replace_from = rel_start + len(expr)
        rewritten = (
            rewritten[:replace_from]
            + re.sub(
                rf"\b{re.escape(temp)}\b",
                expr,
                rewritten[replace_from:],
            )
        )
        if rewritten == statement:
            continue
        return LifetimeLayoutProbe(
            label="assignment-expression-cse-removal-0",
            operator="expression-shape",
            description=(
                f"Remove assignment-in-expression temp `{temp}` and repeat "
                "the natural operand expression."
            ),
            source_text=_replace_body_slice(
                source,
                body_start,
                stmt_start,
                stmt_end,
                rewritten,
            ),
            provenance={
                "kind": "assignment-expression-cse-removal",
                "temp": temp,
                "expr": expr,
            },
        )
    return None


def _probe_distance_component_temps(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    component_re = re.compile(
        rf"\(\s*\((?P<dx>{_DIFF_EXPR_RE})\)\s*\*\s*\((?P=dx)\)\s*\)"
        rf"\s*\+\s*"
        rf"\(\s*\((?P<dy>{_DIFF_EXPR_RE})\)\s*\*\s*\((?P=dy)\)\s*\)",
        re.MULTILINE,
    )
    for match in component_re.finditer(body):
        stmt_start, stmt_end = _statement_bounds_around(body, match.start())
        if stmt_start is None or stmt_end is None:
            continue
        stmt_line_end = body.find("\n", stmt_start)
        if stmt_line_end < 0 or stmt_line_end > stmt_end:
            stmt_line_end = stmt_end
        indent_match = re.match(r"[ \t]*", body[stmt_start:stmt_line_end])
        indent = indent_match.group(0) if indent_match else ""
        dx = _normalize_inline_expr(match.group("dx"))
        dy = _normalize_inline_expr(match.group("dy"))
        replacement = (
            "(ll_probe_dx_0 * ll_probe_dx_0) + "
            "(ll_probe_dy_0 * ll_probe_dy_0)"
        )
        statement = body[stmt_start:stmt_end]
        rel_start = match.start() - stmt_start
        rel_end = match.end() - stmt_start
        insertion = (
            f"{indent}float ll_probe_dx_0 = {dx};\n"
            f"{indent}float ll_probe_dy_0 = {dy};\n"
        )
        rewritten = statement[:rel_start] + replacement + statement[rel_end:]
        return LifetimeLayoutProbe(
            label="distance-component-temps-0",
            operator="expression-shape",
            description="Introduce named dx/dy temps for a repeated squared-distance expression.",
            source_text=_replace_body_slice(
                source,
                body_start,
                stmt_start,
                stmt_end,
                insertion + rewritten,
            ),
            provenance={
                "kind": "distance-component-temps",
                "dx": dx,
                "dy": dy,
            },
        )
    return None


def _probe_abs_branch_discriminator_split(
    source: str,
    body: str,
    body_start: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    expr = rf"(?P<expr>{_DIFF_EXPR_RE})"
    patterns = [
        re.compile(
            rf"(?m)^([ \t]*)(?P<type>float|f32|double)\s+"
            rf"(?P<name>[A-Za-z_]\w*)\s*=\s*{expr}\s*;\n?"
        ),
        re.compile(
            rf"(?m)^([ \t]*)(?P<name>[A-Za-z_]\w*)\s*=\s*{expr}\s*;\n?"
        ),
    ]
    for assign_re in patterns:
        for assign in assign_re.finditer(body):
            indent = assign.group(1)
            value_name = assign.group("name")
            branch_re = re.compile(
                rf"(?m)^([ \t]*)if\s*\(\s*{re.escape(value_name)}\s*>\s*"
                r"0(?:\.0f?)?\s*\)\s*\{"
            )
            branch = branch_re.search(body, assign.end())
            if branch is None:
                continue
            branch_open = body_start + branch.end() - 1
            branch_close = _find_matching_brace(source, branch_open)
            if branch_close is None or branch_close > body_start + len(body):
                continue
            branch_body = source[branch_open + 1:branch_close]
            if not re.search(
                rf"\bif\s*\(\s*{re.escape(value_name)}\s*<\s*0(?:\.0f?)?\s*\)",
                branch_body,
            ):
                continue

            temp = "ll_probe_abs_discriminator_0"
            expression = _normalize_inline_expr(assign.group("expr"))
            if "type" in assign.groupdict() and assign.group("type"):
                type_name = assign.group("type")
                replacement = (
                    f"{indent}{type_name} {temp} = {expression};\n"
                    f"{indent}{type_name} {value_name} = {temp};\n"
                )
            else:
                replacement = (
                    f"{indent}float {temp};\n"
                    f"{indent}{temp} = {expression};\n"
                    f"{indent}{value_name} = {temp};\n"
                )
            branch_header_start = body_start + branch.start()
            branch_header_end = body_start + branch.end()
            branch_header = source[branch_header_start:branch_header_end]
            rewritten_header = re.sub(
                rf"\b{re.escape(value_name)}\b",
                temp,
                branch_header,
                count=1,
            )
            mutated = _replace_absolute_slice(
                source,
                branch_header_start,
                branch_header_end,
                rewritten_header,
            )
            mutated = _replace_body_slice(
                mutated,
                body_start,
                assign.start(),
                assign.end(),
                replacement,
            )
            return LifetimeLayoutProbe(
                label="abs-branch-discriminator-split-0",
                operator="expression-shape",
                description=(
                    f"Split `{value_name}` branch discriminator from the abs "
                    "materialization local."
                ),
                source_text=mutated,
                provenance={
                    "kind": "abs-branch-discriminator-split",
                    "value_local": value_name,
                    "discriminator_local": temp,
                    "expression": expression,
                },
            )
    return None


def _probe_boolean_guard_switch(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> LifetimeLayoutProbe | None:
    if re.search(rf"\bvoid\s+{re.escape(function)}\s*\(", source[:body_start]) is None:
        return None
    for match in re.finditer(r"(?m)^([ \t]*)if\s*\(", body):
        indent = match.group(1)
        condition_start = body_start + match.end() - 1
        condition_end = _find_matching_paren(source, condition_start)
        if condition_end is None or condition_end > body_end:
            continue
        condition = source[condition_start + 1:condition_end].strip()
        if not re.fullmatch(r"[A-Za-z_]\w*\s*\([^{};]*\)", condition):
            continue
        open_brace = source.find("{", condition_end, body_end)
        if open_brace < 0:
            continue
        close_brace = _find_matching_brace(source, open_brace)
        if close_brace is None or close_brace > body_end:
            continue
        if not re.fullmatch(r"\s*return\s*;\s*", source[open_brace + 1:close_brace]):
            continue
        trailing = source[close_brace + 1:body_end].lstrip()
        if trailing.startswith("else"):
            continue
        replacement = (
            f"{indent}switch ({condition}) {{\n"
            f"{indent}case 0:\n"
            f"{indent}    break;\n"
            f"{indent}default:\n"
            f"{indent}    return;\n"
            f"{indent}}}"
        )
        return LifetimeLayoutProbe(
            label="boolean-guard-switch-0",
            operator="guard-shape",
            description=(
                "Rewrite a boolean call guard return as case 0/default switch."
            ),
            source_text=_replace_absolute_slice(
                source,
                body_start + match.start(),
                close_brace + 1,
                replacement,
            ),
            provenance={
                "kind": "boolean-guard-switch",
                "condition": condition,
            },
        )
    return None


def _statement_bounds_around(
    text: str,
    offset: int,
) -> tuple[int | None, int | None]:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find(";", offset)
    if end < 0:
        return None, None
    return start, end + 1


def _normalize_inline_expr(expr: str) -> str:
    return re.sub(r"\s+", " ", expr).replace(" -> ", "->").replace(" . ", ".").strip()


@dataclass(frozen=True)
class _CallReturnCompareChain:
    result_var: str
    compare_var: str
    call_symbol: str
    call_expression: str
    call_line_start: int
    call_expr_start: int
    copy_start: int
    copy_end: int
    first_value: str
    second_value: str
    first_if_start: int
    first_open: int
    first_close: int
    else_start: int
    else_open: int
    else_close: int
    second_if_start: int
    second_open: int
    second_close: int
    indent: str
    inner_indent: str


def _probe_call_return_compare_chain(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
    function: str,
) -> list[LifetimeLayoutProbe]:
    chain = _find_call_return_compare_chain(source, body, body_start, body_end)
    if chain is None:
        return []
    first_body = source[chain.first_open + 1:chain.first_close]
    second_body = source[chain.second_open + 1:chain.second_close]
    original_start = chain.copy_start
    original_end = chain.else_close + 1
    provenance = _call_return_compare_provenance(source, chain)
    probes = [
        LifetimeLayoutProbe(
            label="call-return-compare-switch-0",
            operator="call-return-compare-chain",
            description=(
                f"Rewrite `{chain.compare_var}` call-result compares as a switch."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_call_return_switch(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
        LifetimeLayoutProbe(
            label="call-return-compare-inverted-0",
            operator="call-return-compare-chain",
            description=(
                f"Try the `{chain.second_value}` compare before "
                f"`{chain.first_value}`."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_inverted_compare_chain(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
        LifetimeLayoutProbe(
            label="call-return-compare-copy-in-else-0",
            operator="call-return-compare-chain",
            description=(
                f"Compare `{chain.result_var}` first and copy into "
                f"`{chain.compare_var}` only in the else arm."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_copy_in_else_chain(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
        LifetimeLayoutProbe(
            label="call-return-compare-split-direct-0",
            operator="call-return-compare-chain",
            description=(
                f"Use `{chain.result_var}` for the first compare, then copy "
                f"for the second compare after the first branch."
            ),
            source_text=_replace_absolute_slice(
                source,
                original_start,
                original_end,
                _render_split_direct_chain(chain, first_body, second_body),
            ),
            provenance=provenance,
        ),
    ]
    pointer_probe = _probe_call_return_narrow_pointer(source, chain, provenance)
    if pointer_probe is not None:
        probes.append(pointer_probe)
    return probes


def _find_call_return_compare_chain(
    source: str,
    body: str,
    body_start: int,
    body_end: int,
) -> _CallReturnCompareChain | None:
    assign_re = re.compile(
        r"(?m)^([ \t]*)(?P<result>[A-Za-z_]\w*)\s*=\s*"
        r"(?P<expr>(?P<call>[A-Za-z_]\w*)\s*\([^;\n]*\))\s*;\n"
    )
    for assign in assign_re.finditer(body):
        result_var = assign.group("result")
        rel = assign.end()
        copy_re = re.compile(
            rf"(?m)^([ \t]*)(?P<compare>[A-Za-z_]\w*)\s*=\s*"
            rf"{re.escape(result_var)}\s*;\n"
        )
        copy = copy_re.match(body, rel)
        if copy is None:
            continue
        compare_var = copy.group("compare")
        indent = copy.group(1)
        first_re = re.compile(
            rf"\s*if\s*\(\s*{re.escape(compare_var)}\s*==\s*"
            rf"(?P<value>-?\d+)\s*\)\s*\{{",
            re.MULTILINE,
        )
        first = first_re.match(body, copy.end())
        if first is None:
            continue
        first_open = body_start + first.end() - 1
        first_close = _find_matching_brace(source, first_open)
        if first_close is None or first_close > body_end:
            continue
        else_match = re.match(
            r"\s*else\s*\{",
            source[first_close + 1:body_end],
        )
        if else_match is None:
            continue
        else_start = first_close + 1 + else_match.start()
        else_open = first_close + 1 + else_match.end() - 1
        else_close = _find_matching_brace(source, else_open)
        if else_close is None or else_close > body_end:
            continue
        second_re = re.compile(
            rf"\s*if\s*\(\s*{re.escape(compare_var)}\s*==\s*"
            rf"(?P<value>-?\d+)\s*\)\s*\{{",
            re.MULTILINE,
        )
        second = second_re.match(source, else_open + 1, else_close)
        if second is None:
            continue
        second_open = second.end() - 1
        second_close = _find_matching_brace(source, second_open)
        if second_close is None or second_close > else_close:
            continue
        return _CallReturnCompareChain(
            result_var=result_var,
            compare_var=compare_var,
            call_symbol=assign.group("call"),
            call_expression=assign.group("expr").strip(),
            call_line_start=body_start + assign.start(),
            call_expr_start=body_start + assign.start("expr"),
            copy_start=body_start + copy.start(),
            copy_end=body_start + copy.end(),
            first_value=first.group("value"),
            second_value=second.group("value"),
            first_if_start=body_start + first.start(),
            first_open=first_open,
            first_close=first_close,
            else_start=else_start,
            else_open=else_open,
            else_close=else_close,
            second_if_start=second.start(),
            second_open=second_open,
            second_close=second_close,
            indent=indent,
            inner_indent=indent + "    ",
        )
    return None


def _call_return_compare_provenance(
    source: str,
    chain: _CallReturnCompareChain,
) -> dict:
    line, col = _line_col(source, chain.call_expr_start)
    return {
        "kind": "call-return-compare-chain",
        "call_symbol": chain.call_symbol,
        "call_expression": chain.call_expression,
        "result_var": chain.result_var,
        "compare_var": chain.compare_var,
        "compare_values": [int(chain.first_value), int(chain.second_value)],
        "source_line": line,
        "source_col": col,
    }


def _render_call_return_switch(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.indent}switch ({chain.compare_var}) {{\n"
        f"{chain.indent}case {chain.first_value}: {{"
        f"{first_body}"
        f"{chain.inner_indent}break;\n"
        f"{chain.indent}}}\n"
        f"{chain.indent}case {chain.second_value}: {{"
        f"{second_body}"
        f"{chain.inner_indent}break;\n"
        f"{chain.indent}}}\n"
        f"{chain.indent}}}"
    )


def _render_inverted_compare_chain(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.indent}if ({chain.compare_var} == {chain.second_value}) {{"
        f"{second_body}"
        f"{chain.indent}}} else {{\n"
        f"{chain.inner_indent}if ({chain.compare_var} == {chain.first_value}) {{"
        f"{_indent_block_lines(first_body, chain.inner_indent)}"
        f"{chain.inner_indent}}}\n"
        f"{chain.indent}}}"
    )


def _render_copy_in_else_chain(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}if ({chain.result_var} == {chain.first_value}) {{"
        f"{first_body}"
        f"{chain.indent}}} else {{\n"
        f"{chain.inner_indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.inner_indent}if ({chain.compare_var} == {chain.second_value}) {{"
        f"{_indent_block_lines(second_body, chain.inner_indent)}"
        f"{chain.inner_indent}}}\n"
        f"{chain.indent}}}"
    )


def _render_split_direct_chain(
    chain: _CallReturnCompareChain,
    first_body: str,
    second_body: str,
) -> str:
    return (
        f"{chain.indent}if ({chain.result_var} == {chain.first_value}) {{"
        f"{first_body}"
        f"{chain.indent}}}\n"
        f"{chain.indent}{chain.compare_var} = {chain.result_var};\n"
        f"{chain.indent}if ({chain.compare_var} == {chain.second_value}) {{"
        f"{second_body}"
        f"{chain.indent}}}"
    )


def _probe_call_return_narrow_pointer(
    source: str,
    chain: _CallReturnCompareChain,
    provenance: dict,
) -> LifetimeLayoutProbe | None:
    first_body = source[chain.first_open + 1:chain.first_close]
    body_offset = chain.first_open + 1
    pointer_re = re.compile(
        r"(?m)^([ \t]*)(?:const\s+|volatile\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
        r"(?:\s*\*)+\s+([A-Za-z_]\w*)\s*=\s*[^;\n]+;\n"
    )
    for match in pointer_re.finditer(first_body):
        indent, name = match.groups()
        rel_start = match.start()
        abs_start = body_offset + rel_start
        rel_use_end = _last_line_end_for_identifiers(
            first_body,
            rel_start,
            (name,),
        )
        if rel_use_end is None:
            continue
        abs_use_end = body_offset + _balanced_region_end(
            first_body,
            rel_start,
            rel_use_end,
        )
        region = source[abs_start:abs_use_end]
        wrapped = _wrap_block_text(region, indent)
        return LifetimeLayoutProbe(
            label="call-return-compare-narrow-pointer-0",
            operator="call-return-compare-chain",
            description=(
                f"Narrow dependent pointer `{name}` inside the "
                f"`{chain.compare_var} == {chain.first_value}` branch."
            ),
            source_text=_replace_absolute_slice(source, abs_start, abs_use_end, wrapped),
            provenance={**provenance, "dependent_pointer": name},
        )
    return None


def _replace_absolute_slice(
    source: str,
    start: int,
    end: int,
    replacement: str,
) -> str:
    return source[:start] + replacement + source[end:]


def _line_col(source: str, offset: int) -> tuple[int, int]:
    line = source.count("\n", 0, offset) + 1
    last_newline = source.rfind("\n", 0, offset)
    col = offset + 1 if last_newline < 0 else offset - last_newline
    return line, col


def _leading_local_decl_names(text: str) -> tuple[str, ...]:
    names: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if names:
                continue
            break
        match = _LOCAL_DECL_RE.match(line)
        if match is None:
            break
        names.append(match.group(1))
    return tuple(names)


def _last_line_end_for_identifiers(
    text: str,
    start: int,
    names: tuple[str, ...],
) -> int | None:
    token_re = re.compile(
        r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b"
    )
    last_end: int | None = None
    cursor = start
    for line in text[start:].splitlines(keepends=True):
        line_end = cursor + len(line)
        if token_re.search(line):
            last_end = line_end
        cursor = line_end
    return last_end


def _first_later_line_with_identifier(
    text: str,
    start: int,
    name: str,
) -> int | None:
    token_re = re.compile(r"\b" + re.escape(name) + r"\b")
    cursor = start
    for line in text[start:].splitlines(keepends=True):
        stripped = line.strip()
        if stripped and token_re.search(line):
            return cursor
        cursor += len(line)
    return None


def _paragraph_end(text: str, start: int) -> int:
    cursor = start
    saw_content = False
    for line in text[start:].splitlines(keepends=True):
        if saw_content and not line.strip():
            return cursor
        if line.strip():
            saw_content = True
        cursor += len(line)
    return len(text)


def _block_crosses_shallower_else(block: str, first_line: str) -> bool:
    first_indent_len = len(first_line) - len(first_line.lstrip(" \t"))
    for line in block.splitlines():
        stripped = line.lstrip(" \t")
        if not stripped.startswith("} else"):
            continue
        else_indent_len = len(line) - len(stripped)
        if else_indent_len < first_indent_len:
            return True
    return False


def _declaration_use_region_end(text: str, start: int, name: str) -> int | None:
    last_use_end = _last_line_end_for_identifiers(text, start, (name,))
    if last_use_end is None:
        return None
    return _balanced_region_end(text, start, last_use_end)


def _balanced_region_end(text: str, start: int, min_end: int) -> int:
    cursor = start
    depth = 0
    for line in text[start:].splitlines(keepends=True):
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
        cursor += len(line)
        if cursor >= min_end and depth == 0:
            return cursor
    return len(text)


def _wrap_block_text(text: str, indent: str) -> str:
    inner = _indent_block_lines(text, indent)
    if not inner.endswith("\n"):
        inner += "\n"
    return f"{indent}{{\n{inner}{indent}}}\n"


def _indent_block_lines(text: str, indent: str) -> str:
    inner_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if not line.strip():
            inner_lines.append(line)
        elif line.startswith(indent):
            inner_lines.append(f"{indent}    {line[len(indent):]}")
        else:
            inner_lines.append(f"{indent}    {line}")
    return "".join(inner_lines)


def _outdent_block_lines(text: str, from_indent: str, to_indent: str) -> str:
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith(from_indent):
            lines.append(to_indent + line[len(from_indent):])
        else:
            lines.append(line)
    return "".join(lines)


def _split_top_level_args(args_text: str) -> tuple[str, ...]:
    args: list[str] = []
    start = 0
    depth = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for idx, char in enumerate(args_text):
        if char in pairs:
            depth += 1
        elif char in closing and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            args.append(args_text[start:idx].strip())
            start = idx + 1
    tail = args_text[start:].strip()
    if tail:
        args.append(tail)
    return tuple(args)


def _has_tempizable_arithmetic(expr: str) -> bool:
    expr = expr.strip().replace("->", "")
    return (
        "+" in expr
        or "*" in expr
        or "/" in expr
        or re.search(r"[\w\]\)]\s*-\s*(?:[A-Za-z_]\w*|\d|\()", expr)
        is not None
    )


def _find_matching_brace(source: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(source)):
        char = source[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _find_matching_paren(source: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(source)):
        char = source[idx]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return idx
    return None
