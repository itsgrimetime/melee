"""IR facts layer for `debug suggest-coalesce-source`.

Pure data-extraction over the pre-coloring IR pass + the colorgraph
hook output. Exposes per-virtual facts (first def, use sites,
parameter/physical flags) and the cascade analyzer used by discover
mode. No business logic — checkers consume these facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .colorgraph_parser import ColorgraphSection
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
