"""Copy-lifetime and virtual-to-colorgraph diagnostics for mwcc_debug."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .colorgraph_parser import find_function, parse_hook_events
from .parser import Function, Pass, analyze_function, parse_pcdump


@dataclass(frozen=True)
class InstructionOccurrence:
    """Location of a virtual-register occurrence in a pcode pass."""

    pass_name: str
    block_idx: int
    instr_idx: int
    opcode: str
    operands: str


@dataclass(frozen=True)
class CallReturnOrigin:
    """Source-level origin for a virtual copied from a call return register."""

    call_symbol: str
    call_site: InstructionOccurrence
    copy_chain: tuple[int, ...]
    use_sites: tuple[InstructionOccurrence, ...] = ()
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    source_col: Optional[int] = None
    expression: Optional[str] = None
    assigned_local: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "call_symbol": self.call_symbol,
            "call_site": self.call_site.__dict__,
            "copy_chain": self.copy_chain,
            "use_sites": [site.__dict__ for site in self.use_sites],
            "source_file": self.source_file,
            "source_line": self.source_line,
            "source_col": self.source_col,
            "expression": self.expression,
            "assigned_local": self.assigned_local,
        }


@dataclass(frozen=True)
class VirtualToIGResult:
    """Bridge from a visible pcode virtual register to allocator identity."""

    virtual: int
    found: bool
    status: str
    function: str
    class_id: Optional[int] = None
    ig_idx: Optional[int] = None
    simplify_iter: Optional[int] = None
    color_iter: Optional[int] = None
    assigned_reg: Optional[int] = None
    degree: Optional[int] = None
    flags: Optional[int] = None
    live_range: Optional[tuple[int, int]] = None
    use_count: int = 0
    first_occurrence: Optional[InstructionOccurrence] = None
    last_occurrence: Optional[InstructionOccurrence] = None
    candidate_class_ids: tuple[int, ...] = ()
    call_return_origin: Optional[CallReturnOrigin] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "virtual": self.virtual,
            "found": self.found,
            "status": self.status,
            "function": self.function,
            "class_id": self.class_id,
            "ig_idx": self.ig_idx,
            "simplify_iter": self.simplify_iter,
            "color_iter": self.color_iter,
            "assigned_reg": self.assigned_reg,
            "degree": self.degree,
            "flags": self.flags,
            "live_range": self.live_range,
            "use_count": self.use_count,
            "candidate_class_ids": self.candidate_class_ids,
            "call_return_origin": (
                None if self.call_return_origin is None
                else self.call_return_origin.to_dict()
            ),
            "first_occurrence": (
                None if self.first_occurrence is None
                else self.first_occurrence.__dict__
            ),
            "last_occurrence": (
                None if self.last_occurrence is None
                else self.last_occurrence.__dict__
            ),
            "note": self.note,
        }


@dataclass(frozen=True)
class CopyTraceReport:
    """Lifecycle summary for one pcode copy, e.g. `mr r108,r50`."""

    function: str
    from_virtual: int
    to_virtual: int
    status: str
    first_copy: Optional[InstructionOccurrence]
    last_copy: Optional[InstructionOccurrence]
    from_mapping: VirtualToIGResult
    to_mapping: VirtualToIGResult
    likely_cause: str
    first_absent_pass: Optional[str] = None
    transform_category: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "from_virtual": self.from_virtual,
            "to_virtual": self.to_virtual,
            "status": self.status,
            "first_copy": (
                None if self.first_copy is None else self.first_copy.__dict__
            ),
            "last_copy": (
                None if self.last_copy is None else self.last_copy.__dict__
            ),
            "from_mapping": self.from_mapping.to_dict(),
            "to_mapping": self.to_mapping.to_dict(),
            "likely_cause": self.likely_cause,
            "first_absent_pass": self.first_absent_pass,
            "transform_category": self.transform_category,
            "note": self.note,
        }


_CLASS_ALIASES = {
    "gpr": 0,
    "int": 0,
    "r": 0,
    "fp": 1,
    "fpr": 1,
    "float": 1,
    "f": 1,
}


def _normalize_reg_class(reg_class: Optional[str]) -> Optional[int]:
    if reg_class is None:
        return None
    key = reg_class.strip().lower()
    if key not in _CLASS_ALIASES:
        raise ValueError(
            f"unknown register class {reg_class!r}; expected gpr, int, fp, or fpr"
        )
    return _CLASS_ALIASES[key]


def _reg_kind_for_class_id(class_id: Optional[int]) -> Optional[str]:
    if class_id == 0:
        return "r"
    if class_id == 1:
        return "f"
    return None


def _occurrence(
    pass_name: str,
    block_idx: int,
    instr_idx: int,
    instr,
) -> InstructionOccurrence:
    return InstructionOccurrence(
        pass_name=pass_name,
        block_idx=block_idx,
        instr_idx=instr_idx,
        opcode=instr.opcode,
        operands=instr.operands,
    )


def _virtual_occurrences(
    fn,
    virtual: int,
    *,
    reg_kind: Optional[str] = "r",
) -> list[InstructionOccurrence]:
    out: list[InstructionOccurrence] = []
    for p in fn.passes:
        for block in p.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                if any(
                    reg == virtual and (reg_kind is None or kind == reg_kind)
                    for kind, reg in instr.regs
                ):
                    out.append(InstructionOccurrence(
                        pass_name=p.name,
                        block_idx=block.index,
                        instr_idx=instr_idx,
                        opcode=instr.opcode,
                        operands=instr.operands,
                    ))
    return out


def _infer_class_from_pcode(fn, virtual: int) -> Optional[int]:
    kinds: set[str] = set()
    for p in fn.passes:
        for block in p.blocks:
            for instr in block.instructions:
                for kind, reg in instr.regs:
                    if reg == virtual and kind in {"r", "f"}:
                        kinds.add(kind)
    if kinds == {"r"}:
        return 0
    if kinds == {"f"}:
        return 1
    return None


def _copy_occurrences(fn, from_virtual: int, to_virtual: int) -> list[InstructionOccurrence]:
    out: list[InstructionOccurrence] = []
    for p in fn.passes:
        for block in p.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                regs = [(kind, reg) for kind, reg in instr.regs if kind == "r"]
                if (
                    instr.opcode.lower() == "mr"
                    and len(regs) >= 2
                    and regs[0] == ("r", to_virtual)
                    and regs[1] == ("r", from_virtual)
                ):
                    out.append(InstructionOccurrence(
                        pass_name=p.name,
                        block_idx=block.index,
                        instr_idx=instr_idx,
                        opcode=instr.opcode,
                        operands=instr.operands,
                    ))
    return out


def _pass_has_copy(p, from_virtual: int, to_virtual: int) -> bool:
    for block in p.blocks:
        for instr in block.instructions:
            regs = [(kind, reg) for kind, reg in instr.regs if kind == "r"]
            if (
                instr.opcode.lower() == "mr"
                and len(regs) >= 2
                and regs[0] == ("r", to_virtual)
                and regs[1] == ("r", from_virtual)
            ):
                return True
    return False


def _pass_has_virtual(p, virtual: int) -> bool:
    for block in p.blocks:
        for instr in block.instructions:
            if any(kind == "r" and reg == virtual for kind, reg in instr.regs):
                return True
    return False


def _gpr_regs(instr) -> list[tuple[str, int]]:
    return [(kind, reg) for kind, reg in instr.regs if kind == "r"]


def _mr_source_for_dest(instr, dest_virtual: int) -> Optional[int]:
    regs = _gpr_regs(instr)
    if (
        instr.opcode.lower() == "mr"
        and len(regs) >= 2
        and regs[0] == ("r", dest_virtual)
    ):
        return regs[1][1]
    return None


_NON_WRITING_GPR_OPS = {
    "b",
    "bc",
    "bf",
    "bl",
    "blr",
    "bt",
    "cmp",
    "cmpi",
    "cmpl",
    "cmpli",
}


def _writes_gpr(instr, reg: int) -> bool:
    if instr.opcode.lower().startswith("st"):
        return False
    regs = _gpr_regs(instr)
    if not regs or regs[0] != ("r", reg):
        return False
    return instr.opcode.lower() not in _NON_WRITING_GPR_OPS


def _flatten_pass(pass_: Pass) -> list[tuple[int, int, object]]:
    return [
        (block.index, instr_idx, instr)
        for block in pass_.blocks
        for instr_idx, instr in enumerate(block.instructions)
    ]


def _parse_call_symbol(operands: str) -> Optional[str]:
    token = operands.strip().split(None, 1)[0] if operands.strip() else ""
    token = token.split(",", 1)[0]
    if not token:
        return None
    return token


def _find_recent_call(
    flat: list[tuple[int, int, object]],
    *,
    before_idx: int,
    pass_name: str,
    max_scan: int,
) -> tuple[str, InstructionOccurrence] | None:
    stop = max(-1, before_idx - max_scan)
    for idx in range(before_idx, stop, -1):
        block_idx, instr_idx, instr = flat[idx]
        opcode = instr.opcode.lower()
        if opcode == "bl":
            symbol = _parse_call_symbol(instr.operands)
            if symbol:
                return symbol, _occurrence(pass_name, block_idx, instr_idx, instr)
        if _writes_gpr(instr, 3):
            return None
    return None


def _find_call_in_source(
    call_symbol: str,
    *,
    source_text: Optional[str],
    source_file: Optional[str],
) -> tuple[Optional[str], Optional[int], Optional[int], Optional[str], Optional[str]]:
    if not source_text:
        return None, None, None, None, None
    escaped = re.escape(call_symbol)
    assign_re = re.compile(
        rf"\b(?P<lhs>[A-Za-z_]\w*)\s*=\s*"
        rf"(?P<expr>\b{escaped}\s*\([^;]*?\))"
    )
    call_re = re.compile(rf"(?P<expr>\b{escaped}\s*\([^;]*?\))")
    for line_no, line in enumerate(source_text.splitlines(), start=1):
        match = assign_re.search(line)
        if match:
            return (
                source_file,
                line_no,
                match.start("expr") + 1,
                match.group("expr").strip(),
                match.group("lhs"),
            )
    for line_no, line in enumerate(source_text.splitlines(), start=1):
        match = call_re.search(line)
        if match:
            return (
                source_file,
                line_no,
                match.start("expr") + 1,
                match.group("expr").strip(),
                None,
            )
    return None, None, None, None, None


def _trace_call_return_origin_in_pass(
    pass_: Pass,
    virtual: int,
    *,
    source_text: Optional[str],
    source_file: Optional[str],
    max_hops: int = 8,
    max_scan: int = 16,
) -> Optional[CallReturnOrigin]:
    flat = _flatten_pass(pass_)
    candidate_indices = [
        idx
        for idx, (_block_idx, _instr_idx, instr) in enumerate(flat)
        if _mr_source_for_dest(instr, virtual) is not None
    ]
    for start_idx in candidate_indices:
        chain: list[int] = [virtual]
        current = virtual
        max_idx = start_idx
        for _hop in range(max_hops):
            stop = max(-1, max_idx - max_scan)
            found_idx = None
            source_reg = None
            for idx in range(max_idx, stop, -1):
                instr = flat[idx][2]
                source_reg = _mr_source_for_dest(instr, current)
                if source_reg is not None:
                    found_idx = idx
                    break
                if _writes_gpr(instr, current):
                    break
            if found_idx is None or source_reg is None:
                break
            chain.append(source_reg)
            if source_reg >= 32:
                current = source_reg
                max_idx = found_idx - 1
                continue
            if source_reg != 3:
                break
            call = _find_recent_call(
                flat,
                before_idx=found_idx - 1,
                pass_name=pass_.name,
                max_scan=max_scan,
            )
            if call is None:
                break
            call_symbol, call_site = call
            src_file, line, col, expr, assigned = _find_call_in_source(
                call_symbol,
                source_text=source_text,
                source_file=source_file,
            )
            use_sites = tuple(
                _occurrence(pass_.name, block_idx, instr_idx, instr)
                for block_idx, instr_idx, instr in flat[start_idx + 1:]
                if any(kind == "r" and reg == virtual for kind, reg in instr.regs)
                and _mr_source_for_dest(instr, virtual) is None
            )
            return CallReturnOrigin(
                call_symbol=call_symbol,
                call_site=call_site,
                copy_chain=tuple(chain),
                use_sites=use_sites[:5],
                source_file=src_file,
                source_line=line,
                source_col=col,
                expression=expr,
                assigned_local=assigned,
            )
    return None


def _find_call_return_origin(
    fn: Function,
    virtual: int,
    *,
    reg_kind: Optional[str],
    source_text: Optional[str],
    source_file: Optional[str],
) -> Optional[CallReturnOrigin]:
    if reg_kind not in {None, "r"}:
        return None
    for pass_ in fn.passes:
        if pass_.name == "AFTER REGISTER COLORING":
            break
        origin = _trace_call_return_origin_in_pass(
            pass_,
            virtual,
            source_text=source_text,
            source_file=source_file,
        )
        if origin is not None:
            return origin
    return None


def find_call_return_origin(
    pcdump_text: str,
    function: str,
    virtual: int,
    *,
    reg_class: Optional[str] = "gpr",
    source_text: Optional[str] = None,
    source_file: Optional[str] = None,
) -> Optional[CallReturnOrigin]:
    """Find whether a virtual is copied from a recent call return register."""
    fns = parse_pcdump(pcdump_text, function=function)
    fn = fns[0] if fns else None
    if fn is None:
        return None
    class_id = _normalize_reg_class(reg_class)
    return _find_call_return_origin(
        fn,
        virtual,
        reg_kind=_reg_kind_for_class_id(class_id),
        source_text=source_text,
        source_file=source_file,
    )


def _first_absent_pass(
    fn,
    copies: list[InstructionOccurrence],
    from_virtual: int,
    to_virtual: int,
) -> Optional[str]:
    if not copies:
        return None
    first_copy_pass = copies[0].pass_name
    start_idx = next(
        (idx for idx, p in enumerate(fn.passes) if p.name == first_copy_pass),
        None,
    )
    if start_idx is None:
        return None
    for p in fn.passes[start_idx + 1:]:
        if not _pass_has_copy(p, from_virtual, to_virtual):
            return p.name
    return None


def _class_ambiguity_note(
    virtual: int,
    candidate_class_ids: tuple[int, ...],
    selected_class_id: Optional[int],
    base_note: Optional[str] = None,
) -> Optional[str]:
    if len(candidate_class_ids) <= 1:
        return base_note
    classes = ", ".join(str(class_id) for class_id in candidate_class_ids)
    selected = "none" if selected_class_id is None else str(selected_class_id)
    ambiguity = (
        f"multiple register classes have ig_idx {virtual}: {classes}; "
        f"selected class {selected}"
    )
    if base_note:
        return f"{base_note}; {ambiguity}"
    return ambiguity


def find_virtual_to_ig(
    pcdump_text: str,
    function: str,
    virtual: int,
    *,
    reg_class: Optional[str] = None,
    source_text: Optional[str] = None,
    source_file: Optional[str] = None,
) -> VirtualToIGResult:
    """Find allocator graph identity for a visible pcode virtual register.

    MWCC's GPR virtual names normally correspond to colorgraph `ig_idx` values.
    This function makes that correspondence explicit and also reports when a
    virtual appears in pcode but no longer survives into simplify/colorgraph.
    """
    fns = parse_pcdump(pcdump_text, function=function)
    fn = fns[0] if fns else None
    if fn is None:
        return VirtualToIGResult(
            virtual=virtual,
            found=False,
            status="function-not-found",
            function=function,
            note=f"function {function!r} not found in pcdump",
        )

    requested_class_id = _normalize_reg_class(reg_class)
    inferred_class_id = _infer_class_from_pcode(fn, virtual)
    selected_class_id = (
        requested_class_id if requested_class_id is not None else inferred_class_id
    )
    occurrences = _virtual_occurrences(
        fn,
        virtual,
        reg_kind=_reg_kind_for_class_id(selected_class_id),
    )
    call_return_origin = _find_call_return_origin(
        fn,
        virtual,
        reg_kind=_reg_kind_for_class_id(selected_class_id),
        source_text=source_text,
        source_file=source_file,
    )
    infos = {info.virtual: info for info in analyze_function(fn)}
    info = infos.get(virtual)

    events = find_function(parse_hook_events(pcdump_text), function)
    simplify_iter: Optional[int] = None
    class_id: Optional[int] = None
    candidate_class_ids: tuple[int, ...] = ()
    if events is not None:
        candidate_classes = {
            section.class_id
            for section in events.simplify_sections
            for entry in section.entries
            if entry.ig_idx == virtual
        }
        candidate_classes.update(
            section.class_id
            for section in events.colorgraph_sections
            for decision in section.decisions
            if decision.ig_idx == virtual
        )
        candidate_class_ids = tuple(sorted(candidate_classes))
        for section in events.simplify_sections:
            if (
                selected_class_id is not None
                and section.class_id != selected_class_id
            ):
                continue
            for entry in section.entries:
                if entry.ig_idx == virtual:
                    simplify_iter = entry.iter_idx
                    class_id = section.class_id
                    break
            if simplify_iter is not None:
                break

    if events is not None:
        for section in events.colorgraph_sections:
            if (
                selected_class_id is not None
                and section.class_id != selected_class_id
            ):
                continue
            for decision in section.decisions:
                if decision.ig_idx != virtual:
                    continue
                base_note = None
                if not occurrences:
                    base_note = (
                        f"allocator ig_idx {virtual} reached colorgraph, "
                        f"but no real pcode occurrence was found for r{virtual}"
                    )
                note = _class_ambiguity_note(
                    virtual,
                    candidate_class_ids,
                    section.class_id,
                    base_note,
                )
                return VirtualToIGResult(
                    virtual=virtual,
                    found=True,
                    status="colorgraph",
                    function=function,
                    class_id=section.class_id,
                    ig_idx=decision.ig_idx,
                    simplify_iter=simplify_iter,
                    color_iter=decision.iter_idx,
                    assigned_reg=decision.assigned_reg,
                    degree=decision.degree,
                    flags=decision.flags,
                    live_range=(
                        None if info is None
                        else (info.first_use, info.last_use)
                    ),
                    use_count=0 if info is None else info.use_count,
                    first_occurrence=occurrences[0] if occurrences else None,
                    last_occurrence=occurrences[-1] if occurrences else None,
                    candidate_class_ids=candidate_class_ids,
                    call_return_origin=call_return_origin,
                    note=note,
                )

    if simplify_iter is not None:
        note = _class_ambiguity_note(
            virtual,
            candidate_class_ids,
            class_id,
            "virtual reached simplifygraph but no colorgraph decision was emitted",
        )
        return VirtualToIGResult(
            virtual=virtual,
            found=True,
            status="simplify-only",
            function=function,
            class_id=class_id,
            ig_idx=virtual,
            simplify_iter=simplify_iter,
            live_range=None if info is None else (info.first_use, info.last_use),
            use_count=0 if info is None else info.use_count,
            first_occurrence=occurrences[0] if occurrences else None,
            last_occurrence=occurrences[-1] if occurrences else None,
            candidate_class_ids=candidate_class_ids,
            call_return_origin=call_return_origin,
            note=note,
        )

    if occurrences:
        note = _class_ambiguity_note(
            virtual,
            candidate_class_ids,
            selected_class_id,
            "virtual appears in pcode but not in simplify/colorgraph output",
        )
        return VirtualToIGResult(
            virtual=virtual,
            found=False,
            status="pcode-only",
            function=function,
            live_range=None if info is None else (info.first_use, info.last_use),
            use_count=0 if info is None else info.use_count,
            first_occurrence=occurrences[0],
            last_occurrence=occurrences[-1],
            candidate_class_ids=candidate_class_ids,
            call_return_origin=call_return_origin,
            note=note,
        )

    return VirtualToIGResult(
        virtual=virtual,
        found=False,
        status="not-found",
        function=function,
        candidate_class_ids=candidate_class_ids,
        call_return_origin=call_return_origin,
        note=f"r{virtual} was not found in parsed pcode passes",
    )


def trace_copy_lifetime(
    pcdump_text: str,
    function: str,
    *,
    from_virtual: int,
    to_virtual: int,
    reg_class: Optional[str] = "gpr",
    source_text: Optional[str] = None,
    source_file: Optional[str] = None,
) -> CopyTraceReport:
    """Trace a `mr to,from` copy across pcode and allocator output."""
    from_mapping = find_virtual_to_ig(
        pcdump_text,
        function,
        from_virtual,
        reg_class=reg_class,
        source_text=source_text,
        source_file=source_file,
    )
    to_mapping = find_virtual_to_ig(
        pcdump_text,
        function,
        to_virtual,
        reg_class=reg_class,
        source_text=source_text,
        source_file=source_file,
    )
    fns = parse_pcdump(pcdump_text, function=function)
    fn = fns[0] if fns else None
    copies = [] if fn is None else _copy_occurrences(fn, from_virtual, to_virtual)

    if not copies:
        return CopyTraceReport(
            function=function,
            from_virtual=from_virtual,
            to_virtual=to_virtual,
            status="copy-not-found",
            first_copy=None,
            last_copy=None,
            from_mapping=from_mapping,
            to_mapping=to_mapping,
            likely_cause="copy-not-introduced",
            first_absent_pass=None,
            transform_category=None,
            note=f"no `mr r{to_virtual},r{from_virtual}` was found",
        )

    likely_cause = "copy-survived"
    first_absent = None
    transform_category = "copy-survived"
    note = None
    if fn is not None:
        first_absent = _first_absent_pass(
            fn,
            copies,
            from_virtual,
            to_virtual,
        )
    if to_mapping.status == "pcode-only":
        likely_cause = "removed-before-coloring"
        transform_category = "copy-eliminated-before-coloring"
        note = "copy destination appears in pcode but not simplify/colorgraph"
        if fn is not None and first_absent is not None:
            absent_pass = next(
                (p for p in fn.passes if p.name == first_absent),
                None,
            )
            if absent_pass is not None:
                to_present = _pass_has_virtual(absent_pass, to_virtual)
                from_present = _pass_has_virtual(absent_pass, from_virtual)
                if not to_present and from_present:
                    transform_category = "copy-propagation-or-dead-copy"
                elif to_present:
                    transform_category = "copy-rewritten-before-coloring"
    elif (
        to_mapping.assigned_reg is not None
        and from_mapping.assigned_reg is not None
        and to_mapping.assigned_reg == from_mapping.assigned_reg
    ):
        likely_cause = "coalesced-in-coloring"
        transform_category = "coloring-coalescing"
        note = (
            f"r{to_virtual} and r{from_virtual} both colored to "
            f"r{to_mapping.assigned_reg}"
        )
    elif (
        to_mapping.assigned_reg is not None
        and from_mapping.assigned_reg is not None
        and to_mapping.assigned_reg != from_mapping.assigned_reg
    ):
        likely_cause = "copy-survived-distinct-phys"
        transform_category = "copy-survived"
        note = (
            f"copy destination colored to r{to_mapping.assigned_reg}, "
            f"source colored to r{from_mapping.assigned_reg}"
        )

    return CopyTraceReport(
        function=function,
        from_virtual=from_virtual,
        to_virtual=to_virtual,
        status="copy-found",
        first_copy=copies[0],
        last_copy=copies[-1],
        from_mapping=from_mapping,
        to_mapping=to_mapping,
        likely_cause=likely_cause,
        first_absent_pass=first_absent,
        transform_category=transform_category,
        note=note,
    )


def _copy_pairs(fn) -> list[tuple[int, int, InstructionOccurrence]]:
    out: list[tuple[int, int, InstructionOccurrence]] = []
    for p in fn.passes:
        for block in p.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                regs = [(kind, reg) for kind, reg in instr.regs if kind == "r"]
                if instr.opcode.lower() != "mr" or len(regs) < 2:
                    continue
                to_kind, to_virtual = regs[0]
                from_kind, from_virtual = regs[1]
                if to_kind != "r" or from_kind != "r":
                    continue
                if to_virtual < 32 or from_virtual < 32:
                    continue
                out.append((
                    from_virtual,
                    to_virtual,
                    InstructionOccurrence(
                        pass_name=p.name,
                        block_idx=block.index,
                        instr_idx=instr_idx,
                        opcode=instr.opcode,
                        operands=instr.operands,
                    ),
                ))
    return out


def _copy_pair_set(pcdump_text: str, function: str) -> set[tuple[int, int]]:
    fns = parse_pcdump(pcdump_text, function=function)
    fn = fns[0] if fns else None
    if fn is None:
        return set()
    return {
        (from_virtual, to_virtual)
        for from_virtual, to_virtual, _occurrence in _copy_pairs(fn)
    }


def list_copy_lifetimes(
    pcdump_text: str,
    function: str,
    *,
    involving: Optional[int] = None,
    near_block: Optional[int] = None,
    reg_class: Optional[str] = "gpr",
    source_text: Optional[str] = None,
    source_file: Optional[str] = None,
) -> list[CopyTraceReport]:
    """Discover virtual-register copies and trace each unique pair."""
    fns = parse_pcdump(pcdump_text, function=function)
    fn = fns[0] if fns else None
    if fn is None:
        return []

    pairs: dict[tuple[int, int], list[InstructionOccurrence]] = {}
    for from_virtual, to_virtual, occurrence in _copy_pairs(fn):
        if involving is not None and involving not in {from_virtual, to_virtual}:
            continue
        pairs.setdefault((from_virtual, to_virtual), []).append(occurrence)

    reports: list[CopyTraceReport] = []
    for (from_virtual, to_virtual), occurrences in pairs.items():
        if near_block is not None and not any(
            occ.block_idx == near_block for occ in occurrences
        ):
            continue
        reports.append(trace_copy_lifetime(
            pcdump_text,
            function,
            from_virtual=from_virtual,
            to_virtual=to_virtual,
            reg_class=reg_class,
            source_text=source_text,
            source_file=source_file,
        ))
    return reports


def list_new_copy_lifetimes(
    baseline_pcdump_text: str,
    candidate_pcdump_text: str,
    function: str,
    *,
    involving: Optional[int] = None,
    near_block: Optional[int] = None,
    reg_class: Optional[str] = "gpr",
    source_text: Optional[str] = None,
    source_file: Optional[str] = None,
) -> list[CopyTraceReport]:
    """Trace candidate-only `mr` copies relative to a baseline pcdump."""
    baseline_pairs = _copy_pair_set(baseline_pcdump_text, function)
    reports = list_copy_lifetimes(
        candidate_pcdump_text,
        function,
        involving=involving,
        near_block=near_block,
        reg_class=reg_class,
        source_text=source_text,
        source_file=source_file,
    )
    return [
        report for report in reports
        if (report.from_virtual, report.to_virtual) not in baseline_pairs
    ]
