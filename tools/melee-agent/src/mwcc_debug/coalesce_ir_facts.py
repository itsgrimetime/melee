"""IR facts layer for `debug suggest-coalesce-source`.

Pure data-extraction over the pre-coloring IR pass + the colorgraph
hook output. Exposes per-virtual facts (first def, use sites,
parameter/physical flags) and the cascade analyzer used by discover
mode. No business logic — checkers consume these facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .colorgraph_parser import ColorgraphSection
from .parser import Function, Instruction, Pass
from .symbol_bridge import Binding, BindingBasis, FirstDef


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
