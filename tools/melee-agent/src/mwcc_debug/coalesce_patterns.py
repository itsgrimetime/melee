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

from .coalesce_ir_facts import IrFacts, _blocks_defining, _common_successor


class _HasOperands(Protocol):
    """Anything with an `.operands: str` — both Instruction and FirstDef qualify."""
    operands: str


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


def _immediate_operand(ist: _HasOperands) -> Optional[int]:
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
        if fd.opcode == "addi" and _immediate_operand(fd) == 0:
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
        imm_a = _immediate_operand(fa.first_def)
        imm_b = _immediate_operand(fb.first_def)
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


class AliasSplitPattern:
    """r_b is long-lived (≥4 use sites, spans ≥50% of function's blocks),
    r_a is short-lived (≤3 uses, all in same block). Introducing an alias
    variable just before r_a's first use lets r_a inherit r_b's lifetime
    endpoint so they can coalesce.

    EXCLUSION: if r_a's first-def is already `addi r_a, r_b, 0` or
    `mr r_a, r_b`, DirectIdentityPattern owns the pair and we skip
    (otherwise we'd fire on every direct-identity case).
    """
    name = "alias-split"

    def check(self, facts: IrFacts,
              pair: tuple[int, int]) -> Optional[Suggestion]:
        a, b = pair
        fa = facts.by_virtual.get(a)
        fb = facts.by_virtual.get(b)
        if not fa or not fb or fa.first_def is None or fb.first_def is None:
            return None

        # Conservative bail: if r_b's use_sites is truncated, both numerator
        # and denominator below are understated. Falling back to fall-through
        # is safer than risking a misfire. (Spec §5: checkers should degrade.)
        if fb.use_sites_truncated:
            return None

        # Exclusion: skip if DirectIdentity would fire
        fa_fd = fa.first_def
        if len(fa_fd.regs) >= 2 and fa_fd.regs[1] == ("r", b):
            if fa_fd.opcode == "mr":
                return None
            if fa_fd.opcode == "addi" and _immediate_operand(fa_fd) == 0:
                return None

        # r_b: long-lived
        b_uses = len(fb.use_sites)
        b_blocks = {bi for (bi, _) in fb.use_sites}
        total_blocks = max(1, len(facts.pre_pass.blocks))
        if b_uses < 4:
            return None
        if len(b_blocks) / total_blocks < 0.5:
            return None

        # r_a: short-lived, all in same block
        a_uses = len(fa.use_sites)
        a_blocks = {bi for (bi, _) in fa.use_sites}
        if a_uses > 3:
            return None
        if len(a_blocks) > 1:
            return None
        a_block = next(iter(a_blocks)) if a_blocks else fa.first_def.block_idx

        return Suggestion(
            pattern_name="alias-split",
            summary=(
                f"r{b} is long-lived ({b_uses} uses across {len(b_blocks)} "
                f"blocks); r{a} is short-lived (used only in block B{a_block})"
            ),
            ir_evidence=(
                f"r{b} uses: blocks {sorted(b_blocks)}; "
                f"r{a} uses: block B{a_block}"
            ),
            source_hint=(
                f"Introduce an alias variable before r{a}'s first use:\n"
                f"    <type> tmp = <var_b>;\n"
                f"    use(tmp);  // formerly use(r_a)"
            ),
            catalog_ref="alias-split",
        )


ALL_PATTERNS.append(AliasSplitPattern())


class CommonSubExprPattern:
    """r_a and r_b are defined by structurally-identical IR ops (same
    opcode + same non-destination operand signature). MWCC's CSE should
    have folded them but didn't — typically because the C source
    computes the same expression twice.
    """
    name = "common-subexpr"

    def check(self, facts: IrFacts,
              pair: tuple[int, int]) -> Optional[Suggestion]:
        a, b = pair
        fa = facts.by_virtual.get(a)
        fb = facts.by_virtual.get(b)
        if not fa or not fb or fa.first_def is None or fb.first_def is None:
            return None
        if fa.is_param or fb.is_param:
            return None
        if fa.first_def.opcode != fb.first_def.opcode:
            return None
        # Signature: operands string with destination register stripped
        sig_a = _operand_signature(fa.first_def, a)
        sig_b = _operand_signature(fb.first_def, b)
        if sig_a is None or sig_b is None:
            return None
        if sig_a != sig_b:
            return None
        return Suggestion(
            pattern_name="common-subexpr",
            summary=(
                f"r{a} and r{b} are computed by identical IR ops "
                f"({fa.first_def.opcode} {sig_a})"
            ),
            ir_evidence=(
                f"B{fa.first_def.block_idx}: {fa.first_def.opcode} r{a},{sig_a}; "
                f"B{fb.first_def.block_idx}: {fb.first_def.opcode} r{b},{sig_b}"
            ),
            source_hint=(
                "Hoist the shared expression into a temporary:\n"
                "    <type> shared = <var_b's expr>;\n"
                "    use(shared);  // both places"
            ),
            catalog_ref="subexpr-extract",
        )


def _operand_signature(fd, dest_virtual: int) -> Optional[str]:
    """Return the operands string with the leading destination removed.

    For `lwz r33,44(r34)` with dest_virtual=33 → `44(r34)`.
    For `addi r33,r34,5` with dest_virtual=33 → `r34,5`.
    """
    ops = fd.operands
    prefix = f"r{dest_virtual},"
    if not ops.startswith(prefix):
        return None
    return ops[len(prefix):]


ALL_PATTERNS.append(CommonSubExprPattern())


class TernaryCollapsePattern:
    """r_a is defined in multiple branches that converge at a join block.
    One branch's first-def is a direct copy from r_b. Restructuring the
    if/else into a single ternary assignment lets the coalescer see r_a
    and r_b as move-related.
    """
    name = "ternary-collapse"

    def check(self, facts: IrFacts,
              pair: tuple[int, int]) -> Optional[Suggestion]:
        a, b = pair
        # Find all blocks where r_a is defined (dest of some op).
        defining = _blocks_defining(facts.pre_pass, a)
        if len(defining) < 2:
            return None
        # They must share a single join successor.
        join_idx = _common_successor(defining)
        if join_idx is None:
            return None
        # At least one defining block has `mr r_a, r_b` or `addi r_a, r_b, 0`.
        branch_with_rb = None
        for block in defining:
            for ist in block.instructions:
                if not ist.regs or ist.regs[0] != ("r", a):
                    continue
                if len(ist.regs) < 2 or ist.regs[1] != ("r", b):
                    continue
                if ist.opcode == "mr":
                    branch_with_rb = (block.index, "mr")
                    break
                if ist.opcode == "addi" and _immediate_operand(ist) == 0:
                    branch_with_rb = (block.index, "addi-0")
                    break
            if branch_with_rb:
                break
        if branch_with_rb is None:
            return None

        other_blocks = [blk.index for blk in defining
                        if blk.index != branch_with_rb[0]]
        return Suggestion(
            pattern_name="ternary-collapse",
            summary=(
                f"r{a} is assigned in {len(defining)} branches that converge "
                f"at B{join_idx}; one branch (B{branch_with_rb[0]}) "
                f"already copies from r{b}"
            ),
            ir_evidence=(
                f"B{branch_with_rb[0]}: {branch_with_rb[1]} r{a},r{b}; "
                f"other branches: B{','.join(str(i) for i in other_blocks)} "
                f"join B{join_idx}"
            ),
            source_hint=(
                f"Restructure the if/else into a single assignment:\n"
                f"    var_a = (cond) ? var_b : <other>;"
            ),
            catalog_ref="chained-init",
        )


ALL_PATTERNS.append(TernaryCollapsePattern())
