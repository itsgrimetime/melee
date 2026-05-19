"""Parser for COLORGRAPH DECISIONS / IG CONSTRUCTED / CONSTPROP RAN sections.

These are emitted by the mwcc_debug hooks (Tier 2/3/3.5). Separate from the
pcode-pass parser in parser.py — the hook output has its own structured format
that's easier to diff than the free-form pass dumps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


_COLORGRAPH_HEADER_RE = re.compile(
    r"^COLORGRAPH DECISIONS \(class=(\d+), result=(\d+)(?:, n_nodes=(\d+))?\)"
)
_IG_HEADER_RE = re.compile(r"^IG CONSTRUCTED \(class=(\d+), n_nodes=(\d+)\)")
_CP_HEADER_RE = re.compile(
    r"^CONSTPROP RAN \(changed_flag: before=(-?\d+) after=(-?\d+)\)"
)
_SIMPLIFY_HEADER_RE = re.compile(
    r"^SIMPLIFY GRAPH \(class=(\d+), n_colors=(\d+), n_class_regs=(\d+)\)"
)
_ITER_RE = re.compile(
    r"^\s*(\d+)\s+(-?\d+)\s+r(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+0x([0-9a-fA-F]+)\s*$"
)
# SIMPLIFY row: iter ig_idx degree arraySize 0xflags [notes]
# Notes column is optional / freeform (e.g. "SPILLED").
_SIMPLIFY_ITER_RE = re.compile(
    r"^\s*(\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+0x([0-9a-fA-F]+)\s*(.*?)\s*$"
)
_INTERFERERS_RE = re.compile(r"^\s*interferers:\s*(.*)$")
_FUNCTION_START_RE = re.compile(r"^Starting function\s+(\S+)")


@dataclass
class ColorgraphDecision:
    """One row in a COLORGRAPH DECISIONS table."""

    iter_idx: int
    ig_idx: int  # -1 if linear scan didn't find it in interferencegraph[]
    assigned_reg: int  # physical register (0..31 for GPR, etc.)
    degree: int  # neighbor count at coloring time
    n_interferers: int  # original interferer array size
    flags: int  # IGNode flags (bit 0 = spilled, etc.)
    interferers: list[tuple[int, int]] = field(default_factory=list)
    # (interferer_idx, that_interferer's_assigned_reg) pairs


@dataclass
class ColorgraphSection:
    class_id: int
    result: int
    n_nodes: int
    decisions: list[ColorgraphDecision] = field(default_factory=list)


@dataclass
class IGConstructedEvent:
    class_id: int
    n_nodes: int


@dataclass
class ConstPropEvent:
    changed_before: int
    changed_after: int


@dataclass
class SimplifyEntry:
    """One row in a SIMPLIFY GRAPH table.

    The interpretation: this node was pushed onto the simplification stack
    at position `iter_idx` (0=first into stack, last to be colored;
    equivalently: head of returned linked list = iter 0 = colored FIRST in
    colorgraph's walk). `ig_idx` is the node's index in interferencegraph[],
    or -1 for "physical reg" nodes that aren't part of the virtual-reg IG.
    `spilled` is True if the SPILLED flag (0x08) was set by simplifygraph
    (potential spill marker).
    """

    iter_idx: int
    ig_idx: int
    degree: int  # post-simplification degree (often 0 once neighbors are removed)
    array_size: int  # original interferer count (pre-simplification)
    flags: int
    spilled: bool  # convenience: flags & 0x08


@dataclass
class SimplifySection:
    """One emission of the simplifygraph hook for a (function, class) pair."""

    class_id: int
    n_colors: int
    n_class_regs: int
    entries: list[SimplifyEntry] = field(default_factory=list)


@dataclass
class FunctionEvents:
    """All hook-emitted events for one function in a pcdump."""

    name: str
    colorgraph_sections: list[ColorgraphSection] = field(default_factory=list)
    ig_events: list[IGConstructedEvent] = field(default_factory=list)
    cp_events: list[ConstPropEvent] = field(default_factory=list)
    simplify_sections: list[SimplifySection] = field(default_factory=list)


def parse_hook_events(text: str) -> list[FunctionEvents]:
    """Parse a pcdump.txt for hook-emitted events (COLORGRAPH DECISIONS,
    IG CONSTRUCTED, CONSTPROP RAN), organized by function.

    Returns a list of FunctionEvents in pcdump appearance order. Each
    Function has its events (multiple colorgraph sections — one per
    register class — and matching ig/cp events).
    """
    functions: list[FunctionEvents] = []
    current_func: Optional[FunctionEvents] = None
    current_cg: Optional[ColorgraphSection] = None
    current_simplify: Optional[SimplifySection] = None
    last_decision: Optional[ColorgraphDecision] = None
    # True if next line might be the table header row we should skip
    expect_header_row = False

    lines = text.splitlines()
    for line in lines:
        stripped = line.rstrip()

        m = _FUNCTION_START_RE.match(stripped)
        if m:
            current_func = FunctionEvents(name=m.group(1))
            functions.append(current_func)
            current_cg = None
            current_simplify = None
            last_decision = None
            expect_header_row = False
            continue

        if current_func is None:
            continue  # before first function — ignore

        m = _COLORGRAPH_HEADER_RE.match(stripped)
        if m:
            n_nodes = int(m.group(3)) if m.group(3) else -1
            current_cg = ColorgraphSection(
                class_id=int(m.group(1)),
                result=int(m.group(2)),
                n_nodes=n_nodes,
            )
            current_func.colorgraph_sections.append(current_cg)
            current_simplify = None
            last_decision = None
            expect_header_row = True  # next line will be "iter ig_idx ..."
            continue

        m = _SIMPLIFY_HEADER_RE.match(stripped)
        if m:
            current_simplify = SimplifySection(
                class_id=int(m.group(1)),
                n_colors=int(m.group(2)),
                n_class_regs=int(m.group(3)),
            )
            current_func.simplify_sections.append(current_simplify)
            current_cg = None
            last_decision = None
            expect_header_row = True
            continue

        if expect_header_row:
            expect_header_row = False
            # Don't try to parse the header row as a decision
            continue

        m = _IG_HEADER_RE.match(stripped)
        if m:
            current_func.ig_events.append(IGConstructedEvent(
                class_id=int(m.group(1)),
                n_nodes=int(m.group(2)),
            ))
            current_cg = None
            current_simplify = None
            last_decision = None
            continue

        m = _CP_HEADER_RE.match(stripped)
        if m:
            current_func.cp_events.append(ConstPropEvent(
                changed_before=int(m.group(1)),
                changed_after=int(m.group(2)),
            ))
            current_cg = None
            current_simplify = None
            last_decision = None
            continue

        # Try parsing as a simplify row (only if we're inside a simplify section)
        if current_simplify is not None:
            m = _SIMPLIFY_ITER_RE.match(stripped)
            if m:
                flags = int(m.group(5), 16)
                current_simplify.entries.append(SimplifyEntry(
                    iter_idx=int(m.group(1)),
                    ig_idx=int(m.group(2)),
                    degree=int(m.group(3)),
                    array_size=int(m.group(4)),
                    flags=flags,
                    spilled=bool(flags & 0x08),
                ))
                continue

        # Try parsing as a decision row (only if we're inside a colorgraph section)
        if current_cg is not None:
            m = _ITER_RE.match(stripped)
            if m:
                last_decision = ColorgraphDecision(
                    iter_idx=int(m.group(1)),
                    ig_idx=int(m.group(2)),
                    assigned_reg=int(m.group(3)),
                    degree=int(m.group(4)),
                    n_interferers=int(m.group(5)),
                    flags=int(m.group(6), 16),
                )
                current_cg.decisions.append(last_decision)
                continue

            # Try parsing as an interferers continuation line
            m = _INTERFERERS_RE.match(stripped)
            if m and last_decision is not None:
                # Parse "idx=rN idx=rN ..." pairs
                parts = m.group(1).split()
                pairs = []
                for p in parts:
                    if "=r" not in p:
                        continue
                    idx_str, reg_str = p.split("=r", 1)
                    try:
                        idx = int(idx_str)
                        reg = int(reg_str)
                        pairs.append((idx, reg))
                    except ValueError:
                        continue
                last_decision.interferers = pairs
                continue

    return functions


def find_function(events: list[FunctionEvents], name: str) -> Optional[FunctionEvents]:
    for f in events:
        if f.name == name:
            return f
    return None
