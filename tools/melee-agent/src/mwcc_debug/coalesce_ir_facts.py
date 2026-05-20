"""IR facts layer for `debug suggest-coalesce-source`.

Pure data-extraction over the pre-coloring IR pass + the colorgraph
hook output. Exposes per-virtual facts (first def, use sites,
parameter/physical flags) and the cascade analyzer used by discover
mode. No business logic — checkers consume these facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .colorgraph_parser import ColorgraphDecision, ColorgraphSection
from .parser import Block, Function, Instruction, Pass
from .symbol_bridge import (
    Binding,
    BindingBasis,
    FirstDef,
    find_first_def,
    list_bindings_with_basis,
)


# Cap on use_sites per virtual — keeps memory bounded for huge functions.
# Checkers that need exhaustive counts should consult `use_sites_truncated`
# and degrade or warn.
USE_SITES_CAP = 16


@dataclass
class VirtualFacts:
    """Per-virtual data the pattern checkers consume.

    `is_phys=True` means the slot is actually a physical register
    (number < 32) — the data structure is identical and we keep one
    type for both. Checkers that care about "real" virtuals filter
    by is_phys themselves.
    """
    virtual: int
    first_def: Optional[FirstDef]
    use_sites: list[tuple[int, Instruction]]
    use_sites_truncated: bool
    is_param: bool
    is_phys: bool


@dataclass
class IrFacts:
    """All inputs the pattern checkers need for one function.

    `cg_section` is REQUIRED for discover-mode (analyze_cascade reads
    assignedReg + interferers); pair mode can run with cg_section=None.
    """
    function_name: str
    pre_pass: Pass
    by_virtual: dict[int, VirtualFacts]
    bindings: list[Binding]
    basis: Optional[BindingBasis]
    cg_section: Optional[ColorgraphSection]


def collect(fn: Function, source: str) -> IrFacts:
    """Build IrFacts for `fn` from its pre-coloring pass + source.

    Caller must ensure the function has at least one pre-coloring pass
    (use `fn.last_precolor_pass()` to find it). If none exists, callers
    should abort at the CLI level — this function assumes the data
    is present.

    `cg_section` is left None; the caller populates it from
    `parse_hook_events(text)` + `find_function()` when in discover mode.
    """
    pre_pass = fn.last_precolor_pass()
    if pre_pass is None:
        # No IR detail in the dump; return an empty-ish facts shell.
        return IrFacts(
            function_name=fn.name, pre_pass=Pass(name="(missing)"),
            by_virtual={}, bindings=[], basis=None, cg_section=None,
        )

    # Collect all (kind, num) operand mentions, indexed by virtual number.
    by_virtual: dict[int, VirtualFacts] = {}

    # First pass: discover every virtual mentioned anywhere.
    seen: set[int] = set()
    for block in pre_pass.blocks:
        for ist in block.instructions:
            for kind, num in ist.regs:
                if kind == "r":
                    seen.add(num)

    # Symbol bridge for source-line annotations.
    bindings, basis = list_bindings_with_basis(source, fn.name, pre_pass)

    # Second pass: collect first_def + use_sites for each virtual.
    for v in seen:
        first_def = find_first_def(v, pre_pass)
        use_sites: list[tuple[int, Instruction]] = []
        truncated = False
        for block in pre_pass.blocks:
            for ist in block.instructions:
                # A "use" is any occurrence of the virtual in the operands
                if any(k == "r" and n == v for k, n in ist.regs):
                    if len(use_sites) >= USE_SITES_CAP:
                        truncated = True
                        break
                    use_sites.append((block.index, ist))
            if truncated:
                break

        is_phys = v < 32
        is_param = _is_param(v, first_def, pre_pass, bindings, basis)
        by_virtual[v] = VirtualFacts(
            virtual=v,
            first_def=first_def,
            use_sites=use_sites,
            use_sites_truncated=truncated,
            is_param=is_param,
            is_phys=is_phys,
        )

    return IrFacts(
        function_name=fn.name, pre_pass=pre_pass,
        by_virtual=by_virtual, bindings=bindings, basis=basis,
        cg_section=None,
    )


def _is_param(
    virtual: int,
    first_def: Optional[FirstDef],
    pre_pass: Pass,
    bindings: list[Binding],
    basis: Optional[BindingBasis],
) -> bool:
    """Operational `is_param` test — see §5 of the spec.

    Primary: virtual's first-def is in entry block AND has the form
    `mr rN, rK` where K ∈ {3..10}.

    Fallback: virtual is among the first len(parsed_params) entries of
    sorted(basis.observed_virtuals).
    """
    if virtual < 32:
        return False  # physical regs aren't params
    if first_def is not None and first_def.block_idx == 0:
        if first_def.opcode == "mr":
            # regs[1] is the source register
            # TODO(task-9): use first_def.regs[1] once FirstDef carries it.
            # For now we parse the source register out of the operands string.
            ops = first_def.operands.replace(" ", "")
            parts = ops.split(",")
            if len(parts) >= 2 and parts[1].startswith("r"):
                try:
                    src = int(parts[1][1:])
                    if 3 <= src <= 10:
                        return True
                except ValueError:
                    pass
    # Fallback
    if basis is not None and basis.parsed_params:
        n_params = len(basis.parsed_params)
        prefix = sorted(basis.observed_virtuals)[:n_params]
        if virtual in prefix:
            return True
    return False


def _blocks_defining(pre_pass: Pass, virtual: int) -> list[Block]:
    """Return all blocks where `virtual` is the destination (regs[0]) of
    any instruction. Used by TernaryCollapsePattern for phi-like detection.
    """
    out: list[Block] = []
    for block in pre_pass.blocks:
        for ist in block.instructions:
            if ist.regs and ist.regs[0] == ("r", virtual):
                out.append(block)
                break  # one def per block is enough
    return out


def _common_successor(blocks: list[Block]) -> Optional[int]:
    """Return the single block index that is in EVERY input block's
    successor set, or None if there isn't exactly one such join.
    """
    if not blocks:
        return None
    common = set(blocks[0].succ)
    for b in blocks[1:]:
        common &= set(b.succ)
    if len(common) == 1:
        return next(iter(common))
    return None


# GPR callee-save range. FP analog (f24..f31) handled by class param;
# v1 ships GPR only — see spec §5 limitations.
_GPR_CALLEE_SAVES = list(range(25, 32))  # r25..r31


@dataclass
class CascadeCandidate:
    """One proposed coalesce surfaced by analyze_cascade()."""
    from_virt: int        # ig_idx of the virtual that would be merged away
    to_virt: int          # ig_idx of the virtual it would merge into
    priority_class: str   # "end-of-chain" | "frees-slot"
    depends_on: Optional[tuple[int, int]]  # earlier pair this depends on


def analyze_cascade(facts: IrFacts) -> list[CascadeCandidate]:
    """Identify the longest descending callee-save chain and propose
    coalesces that would shorten it.

    For each cascade-adjacent reg pair, considers all holders coloring
    to those regs (multi-holder per reg is real in pre-allocation
    output) and surfaces the lowest-ig-sum non-interfering combination.
    """
    cg = facts.cg_section
    if cg is None:
        return []

    saves = [
        d for d in cg.decisions if d.assigned_reg in _GPR_CALLEE_SAVES
    ]
    if len(saves) < 2:
        return []
    saves.sort(key=lambda d: -d.assigned_reg)

    asc = sorted({d.assigned_reg for d in saves})
    cascade: list[int] = []
    for i, r in enumerate(asc):
        if i == 0 or r == asc[i - 1] + 1:
            cascade.append(r)
        else:
            break
    if len(cascade) < 2:
        return []

    # Multi-holder: collect ALL decisions per assigned_reg, not just one.
    # Pre-allocation IR routinely has multiple virtuals targeting the
    # same callee-save reg; picking a single representative drops
    # legitimate coalesce candidates.
    by_reg: dict[int, list[ColorgraphDecision]] = {}
    for d in saves:
        by_reg.setdefault(d.assigned_reg, []).append(d)

    def interferes(a: ColorgraphDecision, b: ColorgraphDecision) -> bool:
        a_idxs = {ig for (ig, _) in a.interferers}
        b_idxs = {ig for (ig, _) in b.interferers}
        return b.ig_idx in a_idxs or a.ig_idx in b_idxs

    def pick_pair(
        low_holders: list[ColorgraphDecision],
        high_holders: list[ColorgraphDecision],
    ) -> Optional[tuple[ColorgraphDecision, ColorgraphDecision]]:
        """Return the (low, high) pair with the smallest ig_idx-sum
        whose virtuals don't interfere. None if all combinations
        interfere or either side is empty.
        """
        best: Optional[tuple[ColorgraphDecision, ColorgraphDecision]] = None
        best_key: Optional[tuple[int, int]] = None
        for low in low_holders:
            for high in high_holders:
                if interferes(low, high):
                    continue
                key = (low.ig_idx + high.ig_idx, low.ig_idx)
                if best is None or key < best_key:
                    best = (low, high)
                    best_key = key
        return best

    candidates: list[CascadeCandidate] = []
    end_pair: Optional[CascadeCandidate] = None

    low_reg, mid_reg = cascade[0], cascade[1]
    end_holders = pick_pair(by_reg.get(low_reg, []), by_reg.get(mid_reg, []))
    if end_holders is not None:
        low_d, mid_d = end_holders
        end_pair = CascadeCandidate(
            from_virt=low_d.ig_idx,
            to_virt=mid_d.ig_idx,
            priority_class="end-of-chain",
            depends_on=None,
        )
        candidates.append(end_pair)

    for i in range(1, len(cascade) - 1):
        slot_holders = pick_pair(
            by_reg.get(cascade[i], []),
            by_reg.get(cascade[i + 1], []),
        )
        if slot_holders is None:
            continue
        a_d, b_d = slot_holders
        dep = (end_pair.from_virt, end_pair.to_virt) if end_pair else None
        candidates.append(CascadeCandidate(
            from_virt=a_d.ig_idx,
            to_virt=b_d.ig_idx,
            priority_class="frees-slot",
            depends_on=dep,
        ))

    return candidates
