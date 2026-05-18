"""Simulate MWCC's register-coloring algorithm based on the 7.0 source.

This is a "Tier 2 alternative" — instead of hooking the actual allocator in
mwcceppc.exe (which requires deep RE), we replay the algorithm in Python
using interferences and use-orders extracted from the pcdump.

The algorithm (from compiler_and_linker/BackEnd/PowerPC/RegisterAllocator/
Coloring.c in git.wuffs.org/MWCC):

    while (node) {
        workingMask = volatileRegs;             // caller-save regs initially
        for interferer in node.interferers:
            workingMask &= ~(1 << interferer.assigned_phys);
        if workingMask != 0:
            pick lowest set bit, assign;
        else:
            reg = obtain_nonvolatile_register();
            if reg != -1:
                assign; volatileRegs |= (1 << reg);   // sticky add!
            else:
                spill;
        node = node.next;
    }

Iteration order is determined by simplifygraph (lowest-degree nodes pushed
last on stack, so colored first — Chaitin-style). We approximate by sorting
virtuals by ascending interferer count.

Key insight: when obtain_nonvolatile_register dispenses a callee-save, it's
ADDED to volatileRegs for subsequent virtuals. So later virtuals that don't
interfere with the original holder can reuse that callee-save register —
which is why r32 (highest-degree, colored last) can pick up r26 after r27..r31
have been distributed.

What we DON'T model accurately:
- Caller-save kill at call sites (the real interference graph would have
  every virtual-live-across-a-call interfere with r3..r12; we don't have
  call-site info in pcdump). Our simulator therefore over-predicts
  caller-save usage.
- ABI pinning of r3..r10 for argument passing.
- The exact starting state of obtain_nonvolatile_register (which we infer
  as "start at r27, ascend").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .parser import Function, VirtualRegInfo, analyze_function


# PowerPC ABI: caller-save = r0, r3..r12. r1=SP, r2=TOC reserved.
# Callee-save = r13..r31.
# r0 has special meaning in several PowerPC instructions ("literal 0"), so
# MWCC avoids allocating it for general temps — empirically it shows up only
# for very-short-lived intermediates assigned by the codegen, not by the
# coloring pass. Exclude from our initial volatile pool.
INITIAL_VOLATILE_REGS = {3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
RESERVED_REGS = {1, 2}
N_REAL_GPR = 32

# Opcodes that branch-and-link (i.e., function calls) — virtuals live across
# these positions interfere with caller-save registers.
CALL_OPCODES = {"bl", "bctrl", "bclr", "bcctr", "blrl", "btctr"}

# From empirical observation: obtain_nonvolatile_register starts at r27 and
# ascends. After r31 is allocated, it presumably wraps to r26 and descends.
# (See cleanup-loop pattern in mnVibration_80248644.)
NONVOLATILE_ALLOC_ORDER = [27, 28, 29, 30, 31, 26, 25, 24, 23, 22, 21, 20,
                            19, 18, 17, 16, 15, 14, 13]


@dataclass
class SimDecision:
    """Per-virtual coloring decision made by the simulator."""

    virtual: int
    actual_physical: Optional[int]  # what MWCC actually picked (from pcdump)
    actual_class: str
    predicted_physical: Optional[int]
    used_nonvolatile: bool  # True if obtain_nonvolatile_register was called
    working_mask: set[int]  # the mask at decision time
    interferers_phys: dict[int, int]  # virt → its already-assigned physical
    reasoning: str  # human-readable explanation


def _find_call_positions(fn: Function) -> list[int]:
    """Return the linear positions (in the pre-coloring pass) where call
    instructions appear. Virtuals live across these positions interfere
    with all caller-save registers.
    """
    pre = fn.last_precolor_pass()
    if pre is None:
        return []
    positions = []
    p_idx = 0
    for block in pre.blocks:
        for ist in block.instructions:
            if ist.opcode in CALL_OPCODES:
                positions.append(p_idx)
            p_idx += 1
    return positions


def simulate_function(fn: Function) -> list[SimDecision]:
    """Run the MWCC-style coloring simulation on a function.

    Steps:
    1. Run analyze_function() to get interference data.
    2. Compute call positions; virtuals whose live range crosses a call
       interfere with all caller-save registers (call-site kill).
    3. Sort virtuals by ascending interferer count (Chaitin-style approx).
    4. Walk in order, applying the algorithm.

    Returns one SimDecision per virtual.
    """
    infos = analyze_function(fn)
    if not infos:
        return []

    # Detect call positions to model caller-save kill
    call_positions = _find_call_positions(fn)

    # Index by virtual reg #
    by_virtual: dict[int, VirtualRegInfo] = {info.virtual: info for info in infos}

    def crosses_call(info: VirtualRegInfo) -> bool:
        """Live range [first..last] spans a call? Then caller-save unavailable."""
        return any(info.first_use <= c <= info.last_use for c in call_positions)

    # Iteration order: ascending interferer count, then ascending virtual #
    iter_order = sorted(infos, key=lambda v: (len(v.interferes_with), v.virtual))

    # Simulator state
    volatile_regs: set[int] = set(INITIAL_VOLATILE_REGS)
    nonvolatile_iter_idx = 0  # next index into NONVOLATILE_ALLOC_ORDER
    assignments: dict[int, int] = {}  # virtual → assigned physical

    decisions: list[SimDecision] = []
    for info in iter_order:
        # Compute interferers' physicals
        interferers_phys: dict[int, int] = {}
        for v in info.interferes_with:
            if v in assignments:
                interferers_phys[v] = assignments[v]

        # workingMask = volatile_regs & ~(interferers' physicals)
        working = set(volatile_regs)
        for phys in interferers_phys.values():
            working.discard(phys)

        # If this virtual crosses a call, exclude all caller-save (r3..r12)
        # from workingMask — they get killed by callee-save convention.
        if crosses_call(info):
            working -= INITIAL_VOLATILE_REGS

        if working:
            # Pick lowest available
            chosen = min(working)
            assignments[info.virtual] = chosen
            used_nv = False
            reasoning = (
                f"workingMask had {len(working)} regs available, picked lowest (r{chosen})"
            )
        else:
            # All volatiles taken — obtain nonvolatile
            chosen = None
            while nonvolatile_iter_idx < len(NONVOLATILE_ALLOC_ORDER):
                candidate = NONVOLATILE_ALLOC_ORDER[nonvolatile_iter_idx]
                nonvolatile_iter_idx += 1
                # Only take if not already in interferers (defensive)
                if candidate not in interferers_phys.values():
                    chosen = candidate
                    break
            if chosen is not None:
                assignments[info.virtual] = chosen
                volatile_regs.add(chosen)  # sticky add
                used_nv = True
                reasoning = (
                    f"workingMask empty; obtained nonvolatile r{chosen} "
                    f"(idx {nonvolatile_iter_idx-1} in alloc order)"
                )
            else:
                used_nv = False
                reasoning = "workingMask empty + no nonvolatile available → SPILL"

        decisions.append(SimDecision(
            virtual=info.virtual,
            actual_physical=info.physical,
            actual_class=info.physical_class,
            predicted_physical=chosen,
            used_nonvolatile=used_nv,
            working_mask=working,
            interferers_phys=interferers_phys,
            reasoning=reasoning,
        ))

    return decisions
