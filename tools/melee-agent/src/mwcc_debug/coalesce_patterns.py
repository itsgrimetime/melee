"""Pattern checkers for `debug suggest-coalesce-source`.

Each checker maps a (virt_a, virt_b) pair to a Suggestion when its
IR-level match condition holds. Multiple checkers can match the same
pair — the orchestrator reports all of them. To avoid duplicate
suggestions when one pattern is a strict refinement of another, the
more specific pattern excludes the general case in its own match
condition (see AliasSplitPattern's exclusion).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol

from .coalesce_ir_facts import IrFacts
from .parser import Instruction


@dataclass
class Suggestion:
    """One ranked pattern suggestion."""
    pattern_name: str
    summary: str
    ir_evidence: str
    source_hint: Optional[str]
    catalog_ref: Optional[str]


class Pattern(Protocol):
    """Pattern checker interface."""
    name: str
    def check(self, facts: IrFacts,
              pair: tuple[int, int]) -> Optional[Suggestion]: ...


# Trailing-int regex: matches the last comma-separated token that's a
# bare integer literal (with optional leading minus).
_TRAILING_INT_RE = re.compile(r",(-?\d+)\s*$")


def _immediate_operand(ist: Instruction) -> Optional[int]:
    """Return the trailing integer literal in `ist.operands`, or None.

    Used by checkers that need to distinguish `addi rN, rM, 0` (an
    identity-aliased copy) from `addi rN, rM, K` (an offset arithmetic).
    """
    m = _TRAILING_INT_RE.search(ist.operands)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


# Forward-declared — populated below as each pattern lands.
ALL_PATTERNS: list[Pattern] = []


class DirectIdentityPattern:
    """First-def of r_a is `addi r_a, r_b, 0` or `mr r_a, r_b`.

    r_a is already a direct copy from r_b — the coalescer should have
    merged them, but didn't. The fact it didn't means they interfere
    somewhere; the suggestion explains how to shrink the live range
    so the merge can happen.
    """
    name = "direct-identity"

    def check(self, facts: IrFacts,
              pair: tuple[int, int]) -> Optional[Suggestion]:
        a, b = pair
        if a == b:
            return None
        fa = facts.by_virtual.get(a)
        if fa is None or fa.first_def is None:
            return None
        fd = fa.first_def
        if len(fd.regs) < 2:
            return None
        if fd.regs[0] != ("r", a):
            return None
        if fd.regs[1] != ("r", b):
            return None
        # Skip if source is a physical register (ABI move into/out of virtual)
        if b < 32:
            return None
        if fd.opcode == "mr":
            return self._make_suggestion(facts, pair, fd, "mr")
        if fd.opcode == "addi" and _immediate_operand(
            _instr_from_first_def(fd),
        ) == 0:
            return self._make_suggestion(facts, pair, fd, "addi-0")
        return None

    @staticmethod
    def _make_suggestion(facts, pair, fd, kind):
        a, b = pair
        op_text = "mr" if kind == "mr" else "addi"
        return Suggestion(
            pattern_name="direct-identity",
            summary=f"r{a} is already a direct copy from r{b}",
            ir_evidence=f"B{fd.block_idx}: {op_text} r{a}, r{b}"
                       f"{', 0' if kind == 'addi-0' else ''}",
            source_hint=(
                "Try: shrink the live range of r{a} or r{b} by removing "
                "an intermediate use that's preventing the merge. "
                "alias-split is the closest existing catalog entry — its "
                "'shrink the live range' advice applies."
            ).format(a=a, b=b),
            catalog_ref="alias-split",
        )


def _instr_from_first_def(fd) -> Instruction:
    """Adapter: build an Instruction-shaped object from a FirstDef so
    _immediate_operand() can be called uniformly. The fields used
    (opcode, operands) are present on both types.
    """
    return Instruction(
        opcode=fd.opcode, operands=fd.operands, annotations=[],
        regs=list(fd.regs),
    )


ALL_PATTERNS.append(DirectIdentityPattern())


class ChainInitPattern:
    """Both virtuals initialized to the same value (typically 0) in
    adjacent IR. Combining into a chained C-source assignment collapses
    the two `li` ops and lets MWCC coalesce.
    """
    name = "chain-init"

    def check(self, facts: IrFacts,
              pair: tuple[int, int]) -> Optional[Suggestion]:
        a, b = pair
        fa = facts.by_virtual.get(a)
        fb = facts.by_virtual.get(b)
        if not fa or not fb or fa.first_def is None or fb.first_def is None:
            return None
        if fa.first_def.opcode != "li" or fb.first_def.opcode != "li":
            return None
        imm_a = _immediate_operand(_instr_from_first_def(fa.first_def))
        imm_b = _immediate_operand(_instr_from_first_def(fb.first_def))
        if imm_a is None or imm_a != imm_b:
            return None
        # Adjacency: same block OR within 3 blocks of each other
        if abs(fa.first_def.block_idx - fb.first_def.block_idx) > 3:
            return None
        return Suggestion(
            pattern_name="chain-init",
            summary=f"r{a} and r{b} are both initialized to {imm_a}",
            ir_evidence=(
                f"B{fa.first_def.block_idx}: li r{a}, {imm_a}; "
                f"B{fb.first_def.block_idx}: li r{b}, {imm_b}"
            ),
            source_hint=(
                f"Combine the two assignments into a chain: "
                f"var_a = (var_b = {imm_a});"
            ),
            catalog_ref="chained-init",
        )


ALL_PATTERNS.append(ChainInitPattern())
