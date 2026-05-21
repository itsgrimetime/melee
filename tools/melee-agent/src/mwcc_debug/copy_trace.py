"""Copy-lifetime and virtual-to-colorgraph diagnostics for mwcc_debug."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .colorgraph_parser import find_function, parse_hook_events
from .parser import analyze_function, parse_pcdump


@dataclass(frozen=True)
class InstructionOccurrence:
    """Location of a virtual-register occurrence in a pcode pass."""

    pass_name: str
    block_idx: int
    instr_idx: int
    opcode: str
    operands: str


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
                note = _class_ambiguity_note(
                    virtual,
                    candidate_class_ids,
                    section.class_id,
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
            note=note,
        )

    return VirtualToIGResult(
        virtual=virtual,
        found=False,
        status="not-found",
        function=function,
        candidate_class_ids=candidate_class_ids,
        note=f"r{virtual} was not found in parsed pcode passes",
    )


def trace_copy_lifetime(
    pcdump_text: str,
    function: str,
    *,
    from_virtual: int,
    to_virtual: int,
    reg_class: Optional[str] = "gpr",
) -> CopyTraceReport:
    """Trace a `mr to,from` copy across pcode and allocator output."""
    from_mapping = find_virtual_to_ig(
        pcdump_text,
        function,
        from_virtual,
        reg_class=reg_class,
    )
    to_mapping = find_virtual_to_ig(
        pcdump_text,
        function,
        to_virtual,
        reg_class=reg_class,
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


def list_copy_lifetimes(
    pcdump_text: str,
    function: str,
    *,
    involving: Optional[int] = None,
    near_block: Optional[int] = None,
    reg_class: Optional[str] = "gpr",
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
        ))
    return reports
