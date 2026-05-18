"""Parse mwcc_debug pcdump.txt and derive per-virtual-register info.

The dump format is a sequence of per-function sections, each containing
multiple pass dumps. We care about:

1. The last pre-coloring pass (where virtual regs r32+ appear).
2. The AFTER REGISTER COLORING pass (where physical regs r0-r31 / f0-f31
   appear in the same instruction positions).

By aligning instructions between these two passes, we recover the
virtual→physical mapping, then compute live ranges, use counts, and
interference relationships.

This is heuristic, not exact: pcdump positions don't carry instruction
identity across passes that re-order/eliminate. We do best-effort alignment
within each basic block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, Optional


# PowerPC ABI: r0 is volatile, r1=SP, r2=TOC, r3-r12 = caller-save (volatile),
# r13-r31 = callee-save (non-volatile). Same split for floats: f0-f13 caller,
# f14-f31 callee.
_GPR_CALLER_SAVE = set(range(3, 13))  # r3..r12 — but r1, r2 are reserved
_GPR_CALLEE_SAVE = set(range(13, 32))  # r13..r31


def _is_virtual(reg_num: int) -> bool:
    """MWCC virtual registers are r32+."""
    return reg_num >= 32


def _classify_physical(reg_num: int, is_float: bool) -> str:
    if is_float:
        return "FPR-cs" if reg_num >= 14 else "FPR"
    if reg_num == 0:
        return "GPR-tmp"
    if reg_num in (1, 2):
        return "GPR-rsv"
    if reg_num in _GPR_CALLER_SAVE:
        return "GPR"
    if reg_num in _GPR_CALLEE_SAVE:
        return "GPR-cs"
    return "?"


# Regex for register tokens like r32, r3, f14
_REG_RE = re.compile(r"\b([rf])(\d+)\b")

# Block header line: "B0: Succ={B1 } Pred={} Labels={L0 }"
_BLOCK_RE = re.compile(r"^B(\d+):\s*Succ=\{([^}]*)\}\s*Pred=\{([^}]*)\}\s*Labels=\{([^}]*)\}")

# Function start marker
_FUNC_START_RE = re.compile(r"^Starting function\s+(\S+)")

# Pass marker: any of "BEFORE X", "AFTER X" (caps), or the standalone fn name line
_PASS_MARKERS = (
    "BEFORE GLOBAL OPTIMIZATION",
    "BEFORE COPY PROPAGATION",
    "BEFORE CSE",
    "BEFORE DEAD CODE",
    "BEFORE LOOP",
    "BEFORE PEEPHOLE",
    "BEFORE INSTRUCTION SCHEDULING",
    "BEFORE REGISTER COLORING",
    "AFTER COPY PROPAGATION",
    "AFTER CSE",
    "AFTER DEAD CODE",
    "AFTER LOOP",
    "AFTER PEEPHOLE FORWARD",
    "AFTER PEEPHOLE BACKWARD",
    "AFTER PEEPHOLE",
    "AFTER INSTRUCTION SCHEDULING",
    "AFTER REGISTER COLORING",
    "AFTER CODE MOTION",
    "AFTER CONSTANT PROPAGATION",
    "AFTER VALUE NUMBERING",
    "AFTER VALUE NUMBERING 2",
    "AFTER STRENGTH REDUCTION",
)
_PASS_MARKER_SET = set(_PASS_MARKERS)


@dataclass
class Instruction:
    """One pcode instruction. `regs` is the set of register tokens
    (e.g. {(r, 32), (r, 3), (r, 33)}) — preserves both physical & virtual."""

    opcode: str
    operands: str  # rest of the line after the opcode
    annotations: list[str]  # the "; fIsPtrOp" style annotations
    regs: list[tuple[str, int]]  # in order of appearance in the operand string

    @property
    def virtuals(self) -> set[int]:
        """Just the GPR virtual reg numbers."""
        return {n for (k, n) in self.regs if k == "r" and _is_virtual(n)}

    @property
    def physicals(self) -> set[int]:
        """Just the GPR physical reg numbers."""
        return {n for (k, n) in self.regs if k == "r" and not _is_virtual(n)}


@dataclass
class Block:
    index: int
    succ: list[int]
    pred: list[int]
    labels: list[str]
    instructions: list[Instruction] = field(default_factory=list)


@dataclass
class Pass:
    name: str  # e.g. "AFTER REGISTER COLORING"
    blocks: list[Block] = field(default_factory=list)

    def all_instructions(self) -> Iterator[tuple[int, int, Instruction]]:
        """Yield (block_idx, instr_idx, instruction) tuples."""
        for b in self.blocks:
            for i, ist in enumerate(b.instructions):
                yield (b.index, i, ist)


@dataclass
class Function:
    name: str
    passes: list[Pass] = field(default_factory=list)

    def get_pass(self, name: str) -> Optional[Pass]:
        for p in self.passes:
            if p.name == name:
                return p
        return None

    def last_precolor_pass(self) -> Optional[Pass]:
        """The pass immediately preceding REGISTER COLORING.

        Heuristic: the last pass whose name starts with BEFORE/AFTER and is
        NOT 'AFTER REGISTER COLORING'. In practice this is usually
        'BEFORE REGISTER COLORING' or 'AFTER INSTRUCTION SCHEDULING'.
        """
        last = None
        for p in self.passes:
            if p.name == "AFTER REGISTER COLORING":
                break
            last = p
        return last


@dataclass
class VirtualRegInfo:
    """Per-virtual-register summary, derived by aligning pre-coloring and
    post-coloring passes."""

    virtual: int  # the virtual reg number, e.g. 35
    physical: Optional[int]  # the physical reg it ended up in, or None if unmapped
    physical_class: str  # GPR / GPR-cs / GPR-tmp / unknown
    # Linearized instruction-position live range — both inclusive
    first_use: int
    last_use: int
    use_count: int
    # Other virtuals whose live ranges overlap with this one
    interferes_with: set[int] = field(default_factory=set)
    # The set of physicals NOT used by interferers (i.e. plausible candidates
    # the allocator could have chosen). Computed at analysis time.
    candidates: set[int] = field(default_factory=set)


def _parse_block_header(line: str) -> Optional[Block]:
    m = _BLOCK_RE.match(line.strip())
    if not m:
        return None
    succ = [int(s.lstrip("B")) for s in m.group(2).split() if s.strip()]
    pred = [int(s.lstrip("B")) for s in m.group(3).split() if s.strip()]
    labels = m.group(4).split()
    return Block(index=int(m.group(1)), succ=succ, pred=pred, labels=labels)


def _parse_instruction(line: str) -> Optional[Instruction]:
    """Parse a single instruction line.

    Format: "    OPCODE operands; annot; annot"
    Leading whitespace, opcode, space, rest. Annotations after `;` are
    optional, can be multiple.
    """
    # Must start with whitespace (instructions are indented)
    if not line.startswith("    "):
        return None
    stripped = line.strip()
    if not stripped:
        return None
    # Pseudo-op format "op=0xN ..." vs normal "OPCODE ..."
    parts = stripped.split(None, 1)
    if not parts:
        return None
    opcode = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    # Split off annotations (everything after first `;`)
    if ";" in rest:
        ops_part, anns_part = rest.split(";", 1)
        annotations = [a.strip() for a in anns_part.split(";") if a.strip()]
    else:
        ops_part = rest
        annotations = []
    ops_part = ops_part.strip()
    # Extract all register tokens (preserve order, with duplicates)
    regs: list[tuple[str, int]] = [(m.group(1), int(m.group(2))) for m in _REG_RE.finditer(ops_part)]
    return Instruction(opcode=opcode, operands=ops_part, annotations=annotations, regs=regs)


def parse_pcdump(text: str) -> list[Function]:
    """Parse the full pcdump.txt content into a list of Function objects.

    Each Function contains the per-pass dumps. Best-effort; lines that don't
    match known patterns are silently skipped.
    """
    functions: list[Function] = []
    current_func: Optional[Function] = None
    current_pass: Optional[Pass] = None
    current_block: Optional[Block] = None

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Function start: "Starting function NAME"
        m = _FUNC_START_RE.match(stripped)
        if m:
            current_func = Function(name=m.group(1))
            functions.append(current_func)
            current_pass = None
            current_block = None
            i += 1
            continue

        # Pass marker — appears as a standalone all-caps line
        if stripped in _PASS_MARKER_SET:
            if current_func is None:
                # Pass with no function context — skip
                i += 1
                continue
            current_pass = Pass(name=stripped)
            current_func.passes.append(current_pass)
            current_block = None
            # The line immediately after the pass marker is usually the
            # function name (repeated). Skip it.
            if i + 1 < len(lines) and lines[i + 1].strip() == current_func.name:
                i += 2
            else:
                i += 1
            continue

        # Block header
        block = _parse_block_header(line)
        if block:
            if current_pass is None:
                # Block outside any pass — shouldn't happen, skip
                i += 1
                continue
            current_pass.blocks.append(block)
            current_block = block
            i += 1
            continue

        # Instruction line
        ist = _parse_instruction(line)
        if ist and current_block is not None:
            current_block.instructions.append(ist)
            i += 1
            continue

        # Everything else (pre-pass headers like ":{0005}::::LOOPWEIGHT=0",
        # decorative lines, blank lines, etc.) — skip
        i += 1

    return functions


def analyze_function(fn: Function) -> list[VirtualRegInfo]:
    """Derive per-virtual-register info by aligning pre-coloring & post-coloring.

    Returns a list of VirtualRegInfo, one entry per virtual register that
    appears in the pre-coloring pass.

    Alignment strategy: walk both passes' instructions in linear order
    (block-major, then in-block). When opcodes match at the same position,
    we assume the same logical instruction, and map virtuals→physicals
    position-by-position in the operand list.

    This is heuristic. Coloring shouldn't change opcodes/operand counts,
    but can introduce spill/reload mov instructions. We track this with a
    simple "skip forward to next matching opcode" fallback.
    """
    pre = fn.last_precolor_pass()
    post = fn.get_pass("AFTER REGISTER COLORING")
    if pre is None or post is None:
        return []

    pre_insts = list(pre.all_instructions())
    post_insts = list(post.all_instructions())

    # virt → physical (set, in case allocator splits a virtual across physicals
    # which it shouldn't but we'll be defensive)
    mapping: dict[int, set[int]] = {}
    # virt → list of linear positions where it appears
    positions: dict[int, list[int]] = {}

    # Linear position counter — increments per pre-coloring instruction
    p_idx = 0
    q_idx = 0
    while p_idx < len(pre_insts) and q_idx < len(post_insts):
        _, _, pre_ist = pre_insts[p_idx]
        _, _, post_ist = post_insts[q_idx]
        if pre_ist.opcode == post_ist.opcode and len(pre_ist.regs) == len(post_ist.regs):
            # Aligned: map virtuals position-wise
            for (pk, pn), (qk, qn) in zip(pre_ist.regs, post_ist.regs):
                if pk == "r" and _is_virtual(pn) and qk == "r" and not _is_virtual(qn):
                    mapping.setdefault(pn, set()).add(qn)
                    positions.setdefault(pn, []).append(p_idx)
            # Track virtuals that appeared even if not mapped (e.g. spilled)
            for vk, vn in pre_ist.regs:
                if vk == "r" and _is_virtual(vn):
                    positions.setdefault(vn, []).append(p_idx)
            p_idx += 1
            q_idx += 1
        else:
            # Mismatch: post-pass likely has a spill/reload mov here. Skip post
            # by one and try again. If many mismatches accumulate, also skip pre.
            q_idx += 1
            if q_idx - p_idx > 8:
                p_idx += 1

    # Deduplicate positions per virtual
    for vn in positions:
        positions[vn] = sorted(set(positions[vn]))

    # Build VirtualRegInfo entries (one per virtual seen)
    infos: dict[int, VirtualRegInfo] = {}
    for vn, poses in positions.items():
        first, last = poses[0], poses[-1]
        # Physical: if mapping is 1-to-1, use it; else None
        phys_set = mapping.get(vn, set())
        phys = next(iter(phys_set)) if len(phys_set) == 1 else None
        cls = _classify_physical(phys, is_float=False) if phys is not None else "?"
        infos[vn] = VirtualRegInfo(
            virtual=vn,
            physical=phys,
            physical_class=cls,
            first_use=first,
            last_use=last,
            use_count=len(poses),
        )

    # Compute interferences: two virtuals interfere iff their live ranges overlap
    for a in infos.values():
        for b in infos.values():
            if a.virtual == b.virtual:
                continue
            # Live ranges overlap if max(starts) <= min(ends)
            if max(a.first_use, b.first_use) <= min(a.last_use, b.last_use):
                a.interferes_with.add(b.virtual)

    # Compute candidates: physicals not used by any interfering virtual
    # We only attempt this for virtuals that got a physical assignment.
    all_callee_save = set(_GPR_CALLEE_SAVE)
    all_caller_save = set(_GPR_CALLER_SAVE)
    for vinfo in infos.values():
        if vinfo.physical is None:
            continue
        # What class is this in? Use whatever physical we got
        pool = all_callee_save if vinfo.physical in _GPR_CALLEE_SAVE else all_caller_save
        used_by_interferers: set[int] = set()
        for other_v in vinfo.interferes_with:
            other = infos.get(other_v)
            if other and other.physical is not None and other.physical in pool:
                used_by_interferers.add(other.physical)
        vinfo.candidates = pool - used_by_interferers
        # Sanity: the actual choice should be in candidates
        vinfo.candidates.add(vinfo.physical)

    return sorted(infos.values(), key=lambda v: v.virtual)
