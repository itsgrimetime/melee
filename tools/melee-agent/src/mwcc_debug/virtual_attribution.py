"""Virtual-register source and interference attribution diagnostics."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .colorgraph_parser import find_function, parse_hook_events
from .copy_trace import find_virtual_to_ig
from .parser import Function, Pass, analyze_function, parse_pcdump
from .schedule_explain import (
    _find_global_source_expression,
    _find_source_expression,
)
from .symbol_bridge import find_var_for_virtual, list_bindings

_LOAD_RE = re.compile(
    r"^[^,]+,\s*(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))\s*"
    r"\(\s*r(?P<base>\d+)\s*\)"
)
_COPY_RE = re.compile(r"^r(?P<dest>\d+)\s*,\s*r(?P<src>\d+)\b")
_LOAD_ADDRESS_RE = re.compile(
    r"^r(?P<dest>\d+)\s*,\s*(?P<offset>[-+]?(?:0x[0-9A-Fa-f]+|\d+))"
    r"\s*\(\s*r(?P<base>\d+)\s*\)"
)

_IMPLICIT_TEMP_OPS = {
    "add",
    "addc",
    "adde",
    "addi",
    "addic",
    "addis",
    "and",
    "andc",
    "andi.",
    "andis.",
    "divw",
    "divwu",
    "extsb",
    "extsh",
    "mulli",
    "mullw",
    "neg",
    "or",
    "ori",
    "oris",
    "rlwinm",
    "rlwimi",
    "slw",
    "sraw",
    "srawi",
    "srw",
    "subf",
    "subfc",
    "subfe",
    "xor",
    "xori",
    "xoris",
}
_COMPARE_TEMP_OPS = {"cmp", "cmpi", "cmpl", "cmpli"}
_FPR_TEMP_OPS = {
    "fabs",
    "fadd",
    "fadds",
    "fcmpo",
    "fcmpu",
    "fctiwz",
    "fdiv",
    "fdivs",
    "fmadd",
    "fmadds",
    "fmr",
    "fmsub",
    "fmsubs",
    "fmul",
    "fmuls",
    "fnabs",
    "fneg",
    "fnmadd",
    "fnmsub",
    "fnmsubs",
    "fres",
    "frsp",
    "frsqrte",
    "fsel",
    "fsub",
    "fsubs",
    "lfd",
    "lfs",
    "stfd",
    "stfs",
}


@dataclass(frozen=True)
class InstructionSite:
    pass_name: str
    block_idx: int
    instr_idx: int
    opcode: str
    operands: str


@dataclass(frozen=True)
class SourceAttribution:
    kind: str
    confidence: str
    name: str | None = None
    type: str | None = None
    source_file: str | None = None
    source_line: int | None = None
    source_col: int | None = None
    expression: str | None = None
    base_virtual: int | None = None
    base_var: str | None = None
    base_confidence: str | None = None
    field_offset: int | None = None
    field_name: str | None = None
    first_def: InstructionSite | None = None
    call_symbol: str | None = None
    copy_chain: tuple[int, ...] = ()
    use_sites: tuple[InstructionSite, ...] = ()


@dataclass(frozen=True)
class InterfererAttribution:
    virtual: int
    assigned_reg: int | None
    source: SourceAttribution | None = None


@dataclass(frozen=True)
class PairInterference:
    virtual: int
    other_virtual: int
    colorgraph_interference: bool
    live_overlap: bool
    same_assigned_reg: bool | None
    reason: str


@dataclass(frozen=True)
class VirtualAttribution:
    virtual: int
    status: str
    class_id: int | None
    ig_idx: int | None
    assigned_reg: int | None
    live_range: tuple[int, int] | None
    live_blocks: tuple[int, ...]
    use_count: int
    first_occurrence: InstructionSite | None
    last_occurrence: InstructionSite | None
    source: SourceAttribution | None
    interferers: tuple[InterfererAttribution, ...]
    note: str | None = None


@dataclass(frozen=True)
class VirtualAttributionReport:
    function: str
    virtuals: tuple[VirtualAttribution, ...]
    pair_interferences: tuple[PairInterference, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _instruction_site_from_occurrence(occurrence) -> InstructionSite | None:
    if occurrence is None:
        return None
    return InstructionSite(
        pass_name=occurrence.pass_name,
        block_idx=occurrence.block_idx,
        instr_idx=occurrence.instr_idx,
        opcode=occurrence.opcode,
        operands=occurrence.operands,
    )


def _precolor_passes(fn: Function | None) -> tuple[Pass, ...]:
    if fn is None:
        return ()
    out: list[Pass] = []
    for pass_ in fn.passes:
        if pass_.name == "AFTER REGISTER COLORING":
            break
        out.append(pass_)
    return tuple(out)


def _as_passes(passes: Pass | tuple[Pass, ...] | None) -> tuple[Pass, ...]:
    if passes is None:
        return ()
    if isinstance(passes, tuple):
        return passes
    return (passes,)


def _find_first_def_site(
    virtual: int,
    pre_pass: Pass | tuple[Pass, ...] | None,
    *,
    reg_kind: str = "r",
) -> InstructionSite | None:
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                if not instr.regs:
                    continue
                kind, num = instr.regs[0]
                if kind == reg_kind and num == virtual:
                    return InstructionSite(
                        pass_name=pass_.name,
                        block_idx=block.index,
                        instr_idx=instr_idx,
                        opcode=instr.opcode,
                        operands=instr.operands,
                    )
    return None


def _live_blocks(
    virtual: int,
    pre_pass: Pass | tuple[Pass, ...] | None,
    *,
    reg_kind: str = "r",
) -> tuple[int, ...]:
    blocks: set[int] = set()
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr in block.instructions:
                if any(kind == reg_kind and num == virtual for kind, num in instr.regs):
                    blocks.add(block.index)
                    break
    return tuple(sorted(blocks))


def _pre_occurrence_sites(
    virtual: int,
    pre_pass: Pass | tuple[Pass, ...] | None,
    *,
    reg_kind: str = "r",
) -> tuple[InstructionSite, ...]:
    out: list[InstructionSite] = []
    for pass_ in _as_passes(pre_pass):
        for block in pass_.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                if not any(kind == reg_kind and num == virtual for kind, num in instr.regs):
                    continue
                out.append(InstructionSite(
                    pass_name=pass_.name,
                    block_idx=block.index,
                    instr_idx=instr_idx,
                    opcode=instr.opcode,
                    operands=instr.operands,
                ))
    return tuple(out)


def _bindings_by_virtual(
    source_text: str | None,
    function: str,
    pre_pass: Pass | None,
) -> dict[int, object]:
    if not source_text or pre_pass is None:
        return {}
    try:
        bindings = list_bindings(source_text, function, pre_pass)
    except Exception:
        return {}
    return {
        getattr(binding, "virtual"): binding
        for binding in bindings
        if getattr(binding, "virtual", -1) >= 0
    }


def _source_from_binding(
    binding,
    *,
    source_file: str | None,
) -> SourceAttribution:
    return SourceAttribution(
        kind=str(getattr(binding, "kind", "binding")),
        confidence=str(getattr(binding, "confidence", "best-guess")),
        name=getattr(binding, "var_name", None),
        type=getattr(binding, "type_str", None),
        source_file=source_file,
        source_line=getattr(binding, "decl_line", None),
        expression=getattr(binding, "var_name", None),
    )


def _source_from_load(
    site: InstructionSite,
    *,
    bindings_by_virtual: dict[int, object],
    source_text: str | None,
    source_file: str | None,
) -> SourceAttribution | None:
    if not source_text:
        return None
    match = _LOAD_RE.match(site.operands)
    if match is None:
        return None
    offset = int(match.group("offset"), 0)
    base_virtual = int(match.group("base"))
    base_binding = bindings_by_virtual.get(base_virtual)
    base_var = (
        getattr(base_binding, "var_name", None)
        if base_binding is not None else None
    )
    base_confidence = (
        getattr(base_binding, "confidence", None)
        if base_binding is not None else None
    )
    expression = None
    field_name = None
    line = None
    col = None
    confidence = "field-offset"
    if base_var:
        expression, field_name, line, col, confidence = _find_source_expression(
            source_text,
            base_var=base_var,
            offset=offset,
        )
        if line is None:
            line = getattr(base_binding, "decl_line", None)
    else:
        global_expr = _find_global_source_expression(source_text, offset=offset)
        if global_expr is not None:
            expression, field_name, base_var, line, col = global_expr
            base_confidence = "global-source-expression"
            confidence = "source-expression"
    if expression is None:
        return None
    return SourceAttribution(
        kind="field-load",
        confidence=confidence,
        source_file=source_file,
        source_line=line,
        source_col=col,
        expression=expression,
        base_virtual=base_virtual,
        base_var=base_var,
        base_confidence=base_confidence,
        field_offset=offset,
        field_name=field_name,
        first_def=site,
    )


def _source_from_first_def(site: InstructionSite, *, source_file: str | None) -> SourceAttribution:
    opcode = site.opcode.lower()
    expression = f"{site.opcode} {site.operands}".strip()
    base_virtual = None
    field_offset = None
    kind = "first-def"

    if opcode == "mr":
        match = _COPY_RE.match(site.operands)
        if match:
            base_virtual = int(match.group("src"))
        kind = "copy/coalesce-product"
    elif opcode in _COMPARE_TEMP_OPS:
        kind = "compare-temp"
    elif opcode.startswith(("lw", "lb", "lha", "lhz")):
        match = _LOAD_ADDRESS_RE.match(site.operands)
        if match:
            base_virtual = int(match.group("base"))
            field_offset = int(match.group("offset"), 0)
        kind = "load/store-address"
    elif opcode.startswith(("st",)):
        match = _LOAD_ADDRESS_RE.match(site.operands)
        if match:
            base_virtual = int(match.group("base"))
            field_offset = int(match.group("offset"), 0)
        kind = "load/store-address"
    elif opcode in _IMPLICIT_TEMP_OPS:
        kind = "implicit-temp"
    elif opcode in _FPR_TEMP_OPS:
        kind = "fpr-temp"

    return SourceAttribution(
        kind=kind,
        confidence="pcode-first-def",
        source_file=source_file,
        expression=expression,
        base_virtual=base_virtual,
        field_offset=field_offset,
        first_def=site,
    )


def _source_from_call_return_origin(origin, *, source_file: str | None) -> SourceAttribution:
    return SourceAttribution(
        kind="call-return",
        confidence="copy-chain",
        name=origin.assigned_local,
        source_file=origin.source_file or source_file,
        source_line=origin.source_line,
        source_col=origin.source_col,
        expression=origin.expression or f"{origin.call_symbol}(...)",
        first_def=_instruction_site_from_occurrence(origin.call_site),
        call_symbol=origin.call_symbol,
        copy_chain=origin.copy_chain,
        use_sites=tuple(
            site
            for site in (
                _instruction_site_from_occurrence(use_site)
                for use_site in origin.use_sites
            )
            if site is not None
        ),
    )


def _source_for_virtual(
    virtual: int,
    *,
    function: str,
    pre_pass: Pass | tuple[Pass, ...] | None,
    reg_kind: str,
    source_text: str | None,
    source_file: str | None,
    bindings_by_virtual: dict[int, object],
    call_return_origin=None,
) -> SourceAttribution | None:
    binding = None
    passes = _as_passes(pre_pass)
    binding_pass = passes[-1] if passes else None
    if reg_kind == "r" and source_text and binding_pass is not None:
        try:
            binding = find_var_for_virtual(source_text, function, virtual, binding_pass)
        except Exception:
            binding = None
    if binding is not None:
        return _source_from_binding(binding, source_file=source_file)

    if reg_kind == "r" and call_return_origin is not None:
        return _source_from_call_return_origin(
            call_return_origin,
            source_file=source_file,
        )

    first_def = _find_first_def_site(virtual, pre_pass, reg_kind=reg_kind)
    if first_def is None:
        return None
    load_source = _source_from_load(
        first_def,
        bindings_by_virtual=bindings_by_virtual,
        source_text=source_text,
        source_file=source_file,
    )
    if load_source is not None:
        return load_source
    return _source_from_first_def(first_def, source_file=source_file)


def list_pcode_virtuals(
    pcdump_text: str,
    function: str,
) -> tuple[int, ...]:
    """Return all GPR virtuals observed in the function's pre-coloring pcode."""
    fns = parse_pcdump(pcdump_text, function=function)
    fn: Function | None = fns[0] if fns else None
    if fn is None:
        return ()
    virtuals: set[int] = set()
    for pass_ in _precolor_passes(fn):
        for block in pass_.blocks:
            for instr in block.instructions:
                for kind, num in instr.regs:
                    if kind == "r" and num >= 32:
                        virtuals.add(num)
    return tuple(sorted(virtuals))


def _decision_for(events, class_id: int | None, ig_idx: int | None):
    if events is None or ig_idx is None:
        return None
    for section in events.colorgraph_sections:
        if class_id is not None and section.class_id != class_id:
            continue
        for decision in section.decisions:
            if decision.ig_idx == ig_idx:
                return decision
    return None


def _reg_kind_for_class(class_id: int | None) -> str:
    return "f" if class_id == 1 else "r"


def _decision_interferers(
    decision,
    *,
    by_virtual: dict[int, VirtualAttribution],
) -> tuple[InterfererAttribution, ...]:
    if decision is None:
        return ()
    out: list[InterfererAttribution] = []
    for other_virtual, assigned_reg in decision.interferers:
        other = by_virtual.get(other_virtual)
        out.append(InterfererAttribution(
            virtual=other_virtual,
            assigned_reg=assigned_reg,
            source=None if other is None else other.source,
        ))
    return tuple(out)


def _ranges_overlap(
    a: tuple[int, int] | None,
    b: tuple[int, int] | None,
) -> bool:
    if a is None or b is None:
        return False
    return max(a[0], b[0]) <= min(a[1], b[1])


def _pair_reason(
    left: VirtualAttribution | None,
    right: VirtualAttribution | None,
    *,
    colorgraph_interference: bool,
    live_overlap: bool,
) -> tuple[bool | None, str]:
    if left is None or right is None:
        return None, "one or both virtuals were not found in the report"
    same_assigned = None
    if left.assigned_reg is not None and right.assigned_reg is not None:
        same_assigned = left.assigned_reg == right.assigned_reg

    parts: list[str] = []
    if colorgraph_interference:
        parts.append("colorgraph lists the pair as interferers")
    if live_overlap:
        parts.append(
            "live ranges overlap "
            f"r{left.virtual}={left.live_range} and "
            f"r{right.virtual}={right.live_range}"
        )
    if not parts:
        return same_assigned, "no parsed colorgraph or live-range interference"
    if same_assigned is True:
        return same_assigned, (
            "not forced apart: both virtuals are assigned "
            f"r{left.assigned_reg}; " + "; ".join(parts)
        )
    phys = []
    if left.assigned_reg is not None:
        phys.append(f"r{left.virtual}->r{left.assigned_reg}")
    if right.assigned_reg is not None:
        phys.append(f"r{right.virtual}->r{right.assigned_reg}")
    phys_suffix = f"; assigned {' '.join(phys)}" if phys else ""
    return same_assigned, "cannot coalesce: " + "; ".join(parts) + phys_suffix


def _pair_interference(
    pair: tuple[int, int],
    *,
    by_virtual: dict[int, VirtualAttribution],
    decisions_by_virtual: dict[int, object],
) -> PairInterference:
    left_virtual, right_virtual = pair
    left = by_virtual.get(left_virtual)
    right = by_virtual.get(right_virtual)
    left_decision = decisions_by_virtual.get(left_virtual)
    right_decision = decisions_by_virtual.get(right_virtual)
    left_has_right = (
        left_decision is not None
        and any(v == right_virtual for v, _reg in left_decision.interferers)
    )
    right_has_left = (
        right_decision is not None
        and any(v == left_virtual for v, _reg in right_decision.interferers)
    )
    colorgraph_interference = left_has_right or right_has_left
    live_overlap = _ranges_overlap(
        None if left is None else left.live_range,
        None if right is None else right.live_range,
    )
    same_assigned, reason = _pair_reason(
        left,
        right,
        colorgraph_interference=colorgraph_interference,
        live_overlap=live_overlap,
    )
    return PairInterference(
        virtual=left_virtual,
        other_virtual=right_virtual,
        colorgraph_interference=colorgraph_interference,
        live_overlap=live_overlap,
        same_assigned_reg=same_assigned,
        reason=reason,
    )


def explain_virtuals(
    pcdump_text: str,
    function: str,
    *,
    virtuals: list[int] | tuple[int, ...],
    pairs: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
    source_text: str | None = None,
    source_file: str | None = None,
    reg_class: str | None = "gpr",
) -> VirtualAttributionReport:
    """Explain source provenance, pcdump live blocks, and pair interference."""
    requested: list[int] = []
    seen: set[int] = set()
    for virtual in list(virtuals) + [v for pair in pairs for v in pair]:
        if virtual in seen:
            continue
        seen.add(virtual)
        requested.append(virtual)
    if not requested:
        raise ValueError("at least one virtual or pair is required")

    fns = parse_pcdump(pcdump_text, function=function)
    fn: Function | None = fns[0] if fns else None
    pre_pass = None if fn is None else fn.last_precolor_pass()
    pre_passes = _precolor_passes(fn)
    infos = {} if fn is None else {info.virtual: info for info in analyze_function(fn)}
    bindings = _bindings_by_virtual(source_text, function, pre_pass)
    events = find_function(parse_hook_events(pcdump_text), function)

    provisional: list[VirtualAttribution] = []
    decisions_by_virtual: dict[int, object] = {}
    for virtual in requested:
        mapping = find_virtual_to_ig(
            pcdump_text,
            function,
            virtual,
            reg_class=reg_class,
            source_text=source_text,
            source_file=source_file,
        )
        info = infos.get(virtual)
        live_range = None if info is None else (info.first_use, info.last_use)
        reg_kind = _reg_kind_for_class(mapping.class_id)
        pre_occurrences = _pre_occurrence_sites(
            virtual,
            pre_passes,
            reg_kind=reg_kind,
        )
        first_occurrence = pre_occurrences[0] if pre_occurrences else (
            _instruction_site_from_occurrence(mapping.first_occurrence)
        )
        last_occurrence = pre_occurrences[-1] if pre_occurrences else (
            _instruction_site_from_occurrence(mapping.last_occurrence)
        )
        source = _source_for_virtual(
            virtual,
            function=function,
            pre_pass=pre_passes,
            reg_kind=reg_kind,
            source_text=source_text,
            source_file=source_file,
            bindings_by_virtual=bindings,
            call_return_origin=mapping.call_return_origin,
        )
        decision = _decision_for(events, mapping.class_id, mapping.ig_idx)
        if decision is not None:
            decisions_by_virtual[virtual] = decision
        provisional.append(VirtualAttribution(
            virtual=virtual,
            status=mapping.status,
            class_id=mapping.class_id,
            ig_idx=mapping.ig_idx,
            assigned_reg=mapping.assigned_reg,
            live_range=live_range,
            live_blocks=_live_blocks(virtual, pre_passes, reg_kind=reg_kind),
            use_count=len(pre_occurrences) if info is None else info.use_count,
            first_occurrence=first_occurrence,
            last_occurrence=last_occurrence,
            source=source,
            interferers=(),
            note=mapping.note,
        ))

    by_virtual = {entry.virtual: entry for entry in provisional}
    with_interferers: list[VirtualAttribution] = []
    for entry in provisional:
        decision = decisions_by_virtual.get(entry.virtual)
        with_interferers.append(VirtualAttribution(
            virtual=entry.virtual,
            status=entry.status,
            class_id=entry.class_id,
            ig_idx=entry.ig_idx,
            assigned_reg=entry.assigned_reg,
            live_range=entry.live_range,
            live_blocks=entry.live_blocks,
            use_count=entry.use_count,
            first_occurrence=entry.first_occurrence,
            last_occurrence=entry.last_occurrence,
            source=entry.source,
            interferers=_decision_interferers(decision, by_virtual=by_virtual),
            note=entry.note,
        ))
    by_virtual = {entry.virtual: entry for entry in with_interferers}
    pair_reports = tuple(
        _pair_interference(
            pair,
            by_virtual=by_virtual,
            decisions_by_virtual=decisions_by_virtual,
        )
        for pair in pairs
    )
    return VirtualAttributionReport(
        function=function,
        virtuals=tuple(with_interferers),
        pair_interferences=pair_reports,
    )


def render_virtual_attribution_text(report: VirtualAttributionReport) -> str:
    lines: list[str] = [f"explain-virtual - {report.function}"]
    for entry in report.virtuals:
        phys = "?" if entry.assigned_reg is None else f"r{entry.assigned_reg}"
        live = (
            "?"
            if entry.live_range is None
            else f"{entry.live_range[0]}..{entry.live_range[1]}"
        )
        blocks = (
            "-"
            if not entry.live_blocks
            else ",".join(f"B{block}" for block in entry.live_blocks)
        )
        lines.append(
            f"- r{entry.virtual}: status={entry.status} "
            f"ig={entry.ig_idx if entry.ig_idx is not None else '?'} "
            f"phys={phys} live={live} blocks={blocks}"
        )
        if entry.note:
            lines.append(f"  note:   {entry.note}")
        if entry.source is not None:
            source = entry.source
            loc = ""
            if source.source_file and source.source_line is not None:
                loc = f" {source.source_file}:{source.source_line}"
                if source.source_col is not None:
                    loc += f":{source.source_col}"
            expr = source.expression or source.name or "?"
            lines.append(
                f"  source:{loc} {expr} "
                f"({source.kind}, {source.confidence})"
            )
            if source.base_virtual is not None:
                base = source.base_var or "?"
                lines.append(
                    f"  base:   r{source.base_virtual} {base} "
                    f"offset=0x{source.field_offset:X}"
                    if source.field_offset is not None
                    else f"  base:   r{source.base_virtual} {base}"
                )
            if source.first_def is not None:
                site = source.first_def
                lines.append(
                    "  first:  "
                    f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
                    f"{site.opcode} {site.operands}"
                )
            if source.copy_chain:
                chain = " <- ".join(f"r{reg}" for reg in source.copy_chain)
                lines.append(f"  chain:  {chain}")
            if source.use_sites:
                for site in source.use_sites[:3]:
                    lines.append(
                        "  use:    "
                        f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
                        f"{site.opcode} {site.operands}"
                    )
        if entry.interferers:
            rendered = []
            for interferer in entry.interferers:
                assigned = (
                    "?"
                    if interferer.assigned_reg is None
                    else f"r{interferer.assigned_reg}"
                )
                rendered.append(f"r{interferer.virtual}->{assigned}")
            lines.append(f"  cg-int: {', '.join(rendered)}")
    if report.pair_interferences:
        lines.append("Pairs:")
        for pair in report.pair_interferences:
            lines.append(
                f"- r{pair.virtual}/r{pair.other_virtual}: {pair.reason}"
            )
    return "\n".join(lines)
