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
            "note": self.note,
        }


def _virtual_occurrences(fn, virtual: int) -> list[InstructionOccurrence]:
    out: list[InstructionOccurrence] = []
    for p in fn.passes:
        for block in p.blocks:
            for instr_idx, instr in enumerate(block.instructions):
                if any(kind == "r" and reg == virtual for kind, reg in instr.regs):
                    out.append(InstructionOccurrence(
                        pass_name=p.name,
                        block_idx=block.index,
                        instr_idx=instr_idx,
                        opcode=instr.opcode,
                        operands=instr.operands,
                    ))
    return out


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


def find_virtual_to_ig(
    pcdump_text: str,
    function: str,
    virtual: int,
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

    occurrences = _virtual_occurrences(fn, virtual)
    infos = {info.virtual: info for info in analyze_function(fn)}
    info = infos.get(virtual)

    events = find_function(parse_hook_events(pcdump_text), function)
    simplify_iter: Optional[int] = None
    class_id: Optional[int] = None
    if events is not None:
        for section in events.simplify_sections:
            for entry in section.entries:
                if entry.ig_idx == virtual:
                    simplify_iter = entry.iter_idx
                    class_id = section.class_id
                    break
            if simplify_iter is not None:
                break

    if events is not None:
        for section in events.colorgraph_sections:
            for decision in section.decisions:
                if decision.ig_idx != virtual:
                    continue
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
                )

    if simplify_iter is not None:
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
            note="virtual reached simplifygraph but no colorgraph decision was emitted",
        )

    if occurrences:
        return VirtualToIGResult(
            virtual=virtual,
            found=False,
            status="pcode-only",
            function=function,
            live_range=None if info is None else (info.first_use, info.last_use),
            use_count=0 if info is None else info.use_count,
            first_occurrence=occurrences[0],
            last_occurrence=occurrences[-1],
            note="virtual appears in pcode but not in simplify/colorgraph output",
        )

    return VirtualToIGResult(
        virtual=virtual,
        found=False,
        status="not-found",
        function=function,
        note=f"r{virtual} was not found in parsed pcode passes",
    )


def trace_copy_lifetime(
    pcdump_text: str,
    function: str,
    *,
    from_virtual: int,
    to_virtual: int,
) -> CopyTraceReport:
    """Trace a `mr to,from` copy across pcode and allocator output."""
    from_mapping = find_virtual_to_ig(pcdump_text, function, from_virtual)
    to_mapping = find_virtual_to_ig(pcdump_text, function, to_virtual)
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
            note=f"no `mr r{to_virtual},r{from_virtual}` was found",
        )

    likely_cause = "copy-survived"
    note = None
    if to_mapping.status == "pcode-only":
        likely_cause = "removed-before-coloring"
        note = "copy destination appears in pcode but not simplify/colorgraph"
    elif (
        to_mapping.assigned_reg is not None
        and from_mapping.assigned_reg is not None
        and to_mapping.assigned_reg == from_mapping.assigned_reg
    ):
        likely_cause = "coalesced-in-coloring"
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
        note=note,
    )
