"""Tests for per-pattern coalesce checkers."""

from __future__ import annotations

import pytest

from src.mwcc_debug.coalesce_patterns import (
    ALL_PATTERNS,
    Pattern,
    Suggestion,
    _immediate_operand,
)
from src.mwcc_debug.parser import Instruction


def test_suggestion_dataclass_shape() -> None:
    """Suggestion captures the fields the renderer consumes."""
    s = Suggestion(
        pattern_name="direct-identity",
        summary="r53 already copies from r34",
        ir_evidence="B5: addi r53, r34, 0",
        source_hint=None,
        catalog_ref="alias-split",
    )
    assert s.pattern_name == "direct-identity"


# Skipped until Tasks 9–13 add each checker; un-skipped in Task 13.
@pytest.mark.skip(reason="checkers added in Tasks 9-13; final assertion enabled in Task 13")
def test_all_patterns_initial_set() -> None:
    """ALL_PATTERNS should list exactly the five v1 checkers."""
    names = {p.name for p in ALL_PATTERNS}
    assert names == {
        "direct-identity", "chain-init", "alias-split",
        "common-subexpr", "ternary-collapse",
    }


def test_immediate_operand_parses_trailing_int() -> None:
    """_immediate_operand picks the trailing integer literal."""
    ist = Instruction(opcode="addi", operands="r53,r34,0",
                      annotations=[], regs=[("r", 53), ("r", 34)])
    assert _immediate_operand(ist) == 0

    ist = Instruction(opcode="li", operands="r33,42",
                      annotations=[], regs=[("r", 33)])
    assert _immediate_operand(ist) == 42

    ist = Instruction(opcode="mr", operands="r53,r34",
                      annotations=[], regs=[("r", 53), ("r", 34)])
    assert _immediate_operand(ist) is None


from src.mwcc_debug.coalesce_ir_facts import IrFacts, VirtualFacts
from src.mwcc_debug.coalesce_patterns import DirectIdentityPattern
from src.mwcc_debug.parser import Block, Pass
from src.mwcc_debug.symbol_bridge import FirstDef


def _facts_with(virtual_facts: dict) -> IrFacts:
    return IrFacts(
        function_name="f",
        pre_pass=Pass(name="X"),
        by_virtual=virtual_facts,
        bindings=[],
        basis=None,
        cg_section=None,
    )


def _vf(virtual, first_def, *, is_phys=False, is_param=False,
        use_sites=None):
    return VirtualFacts(
        virtual=virtual, first_def=first_def,
        use_sites=use_sites or [], use_sites_truncated=False,
        is_param=is_param, is_phys=is_phys,
    )


def test_direct_identity_matches_addi_zero() -> None:
    """First-def `addi r53, r34, 0` → DirectIdentity fires."""
    fd = FirstDef(block_idx=5, opcode="addi", operands="r53,r34,0",
                  annotations=[])
    # We also need regs on the underlying Instruction — but find_first_def
    # exposes only opcode/operands/annotations. The pattern uses
    # _immediate_operand which parses operands directly.
    # However the spec says regs[0]==dest, regs[1]==source check is done.
    # Our pattern looks at the underlying instruction's `regs`, so we
    # need to wire that through. For test purposes, attach a synthetic
    # instruction to the FirstDef via a side-channel — see Task 9 impl.
    fd.regs = [("r", 53), ("r", 34)]  # type: ignore[attr-defined]
    facts = _facts_with({53: _vf(53, fd)})
    p = DirectIdentityPattern()
    s = p.check(facts, (53, 34))
    assert s is not None
    assert s.pattern_name == "direct-identity"


def test_direct_identity_skips_addi_nonzero() -> None:
    """First-def `addi r53, r34, 8` → NOT identity (offset arithmetic)."""
    fd = FirstDef(block_idx=5, opcode="addi", operands="r53,r34,8",
                  annotations=[])
    fd.regs = [("r", 53), ("r", 34)]  # type: ignore[attr-defined]
    facts = _facts_with({53: _vf(53, fd)})
    s = DirectIdentityPattern().check(facts, (53, 34))
    assert s is None


def test_direct_identity_skips_wrong_source_register() -> None:
    """First-def `addi r53, r35, 0` → not from r34; pair (53,34) fails."""
    fd = FirstDef(block_idx=5, opcode="addi", operands="r53,r35,0",
                  annotations=[])
    fd.regs = [("r", 53), ("r", 35)]  # type: ignore[attr-defined]
    facts = _facts_with({53: _vf(53, fd)})
    s = DirectIdentityPattern().check(facts, (53, 34))
    assert s is None


def test_direct_identity_skips_missing_first_def() -> None:
    """Virtual not defined anywhere → no match."""
    facts = _facts_with({53: _vf(53, first_def=None)})
    s = DirectIdentityPattern().check(facts, (53, 34))
    assert s is None


def test_direct_identity_skips_self_pair() -> None:
    """Pair (a, a) is a no-op coalesce — pattern must not fire."""
    fd = FirstDef(block_idx=0, opcode="mr", operands="r53,r53",
                  annotations=[], regs=[("r", 53), ("r", 53)])
    facts = _facts_with({53: _vf(53, fd)})
    assert DirectIdentityPattern().check(facts, (53, 53)) is None


def test_direct_identity_skips_physical_source() -> None:
    """First-def `mr r53, r3` is an ABI move, not inter-virtual coalesce."""
    fd = FirstDef(block_idx=0, opcode="mr", operands="r53,r3",
                  annotations=[], regs=[("r", 53), ("r", 3)])
    facts = _facts_with({53: _vf(53, fd)})
    assert DirectIdentityPattern().check(facts, (53, 3)) is None


from src.mwcc_debug.coalesce_patterns import ChainInitPattern


def test_chain_init_matches_same_block_same_immediate() -> None:
    """Two adjacent `li r_X, 0` in the same block → ChainInit fires."""
    fd_a = FirstDef(block_idx=2, opcode="li", operands="r33,0",
                    annotations=[], regs=[("r", 33)])
    fd_b = FirstDef(block_idx=2, opcode="li", operands="r34,0",
                    annotations=[], regs=[("r", 34)])
    facts = _facts_with({
        33: _vf(33, fd_a),
        34: _vf(34, fd_b),
    })
    s = ChainInitPattern().check(facts, (33, 34))
    assert s is not None
    assert s.pattern_name == "chain-init"


def test_chain_init_skips_different_immediates() -> None:
    """`li r33,0` vs `li r34,5` → not a chain-init."""
    fd_a = FirstDef(block_idx=2, opcode="li", operands="r33,0",
                    annotations=[], regs=[("r", 33)])
    fd_b = FirstDef(block_idx=2, opcode="li", operands="r34,5",
                    annotations=[], regs=[("r", 34)])
    facts = _facts_with({33: _vf(33, fd_a), 34: _vf(34, fd_b)})
    assert ChainInitPattern().check(facts, (33, 34)) is None


def test_chain_init_skips_blocks_too_far_apart() -> None:
    """Defs in unrelated blocks (distance > 3) → not chain-init."""
    fd_a = FirstDef(block_idx=0, opcode="li", operands="r33,0",
                    annotations=[], regs=[("r", 33)])
    fd_b = FirstDef(block_idx=10, opcode="li", operands="r34,0",
                    annotations=[], regs=[("r", 34)])
    facts = _facts_with({33: _vf(33, fd_a), 34: _vf(34, fd_b)})
    assert ChainInitPattern().check(facts, (33, 34)) is None


def test_chain_init_skips_non_li_opcode() -> None:
    """`addi r33, r0, 0` looks similar but isn't `li` → skip."""
    fd_a = FirstDef(block_idx=2, opcode="addi", operands="r33,r0,0",
                    annotations=[], regs=[("r", 33), ("r", 0)])
    fd_b = FirstDef(block_idx=2, opcode="li", operands="r34,0",
                    annotations=[], regs=[("r", 34)])
    facts = _facts_with({33: _vf(33, fd_a), 34: _vf(34, fd_b)})
    assert ChainInitPattern().check(facts, (33, 34)) is None


from src.mwcc_debug.coalesce_patterns import AliasSplitPattern
from src.mwcc_debug.parser import Block


def _mk_use(block_idx, opcode="addi", operands="r33,r32,1"):
    """Construct (block_idx, Instruction) for VirtualFacts.use_sites."""
    return (block_idx, Instruction(
        opcode=opcode, operands=operands, annotations=[],
        regs=[("r", 33), ("r", 32)],
    ))


def _pre_pass_with_blocks(n_blocks):
    pp = Pass(name="X")
    pp.blocks = [Block(index=i, succ=[], pred=[], labels=[])
                 for i in range(n_blocks)]
    return pp


def test_alias_split_matches_long_short_pair() -> None:
    """r_b long-lived (5 blocks in 8-block fn), r_a short (all in B7)."""
    fd_long = FirstDef(block_idx=0, opcode="li", operands="r32,5",
                       annotations=[], regs=[("r", 32)])
    fd_short = FirstDef(block_idx=7, opcode="addi", operands="r33,r32,1",
                        annotations=[], regs=[("r", 33), ("r", 32)])
    facts = IrFacts(
        function_name="f",
        pre_pass=_pre_pass_with_blocks(8),
        by_virtual={
            32: _vf(32, fd_long, use_sites=[
                _mk_use(0), _mk_use(1), _mk_use(2), _mk_use(5), _mk_use(7),
            ]),
            33: _vf(33, fd_short, use_sites=[_mk_use(7), _mk_use(7)]),
        },
        bindings=[], basis=None, cg_section=None,
    )
    s = AliasSplitPattern().check(facts, (33, 32))
    assert s is not None
    assert s.pattern_name == "alias-split"


def test_alias_split_skips_when_a_also_long_lived() -> None:
    """Both virtuals long-lived → no split makes sense."""
    fd_a = FirstDef(block_idx=0, opcode="li", operands="r33,5",
                    annotations=[], regs=[("r", 33)])
    fd_b = FirstDef(block_idx=0, opcode="li", operands="r32,5",
                    annotations=[], regs=[("r", 32)])
    facts = IrFacts(
        function_name="f",
        pre_pass=_pre_pass_with_blocks(8),
        by_virtual={
            32: _vf(32, fd_b, use_sites=[
                _mk_use(0), _mk_use(2), _mk_use(4), _mk_use(6),
            ]),
            33: _vf(33, fd_a, use_sites=[
                _mk_use(0), _mk_use(2), _mk_use(4), _mk_use(6),
            ]),
        },
        bindings=[], basis=None, cg_section=None,
    )
    assert AliasSplitPattern().check(facts, (33, 32)) is None


def test_alias_split_skips_when_b_used_too_few() -> None:
    """r_b must have ≥ 4 use sites; 3 isn't enough."""
    fd_b = FirstDef(block_idx=0, opcode="li", operands="r32,5",
                    annotations=[], regs=[("r", 32)])
    fd_a = FirstDef(block_idx=7, opcode="addi", operands="r33,r32,1",
                    annotations=[], regs=[("r", 33), ("r", 32)])
    facts = IrFacts(
        function_name="f",
        pre_pass=_pre_pass_with_blocks(8),
        by_virtual={
            32: _vf(32, fd_b, use_sites=[_mk_use(0), _mk_use(2), _mk_use(7)]),
            33: _vf(33, fd_a, use_sites=[_mk_use(7)]),
        },
        bindings=[], basis=None, cg_section=None,
    )
    assert AliasSplitPattern().check(facts, (33, 32)) is None


def test_alias_split_excludes_direct_identity_case() -> None:
    """If r_a's first-def is `addi r_a, r_b, 0`, DirectIdentity owns this
    pair; AliasSplit should not also fire."""
    fd_a_identity = FirstDef(
        block_idx=7, opcode="addi", operands="r33,r32,0",
        annotations=[], regs=[("r", 33), ("r", 32)],
    )
    fd_b = FirstDef(block_idx=0, opcode="li", operands="r32,5",
                    annotations=[], regs=[("r", 32)])
    facts = IrFacts(
        function_name="f",
        pre_pass=_pre_pass_with_blocks(8),
        by_virtual={
            32: _vf(32, fd_b, use_sites=[
                _mk_use(0), _mk_use(1), _mk_use(2), _mk_use(5), _mk_use(7),
            ]),
            33: _vf(33, fd_a_identity, use_sites=[_mk_use(7)]),
        },
        bindings=[], basis=None, cg_section=None,
    )
    # AliasSplit's exclusion: r_a is not already a direct copy of r_b
    assert AliasSplitPattern().check(facts, (33, 32)) is None


from src.mwcc_debug.coalesce_patterns import CommonSubExprPattern


def test_common_subexpr_matches_identical_ops() -> None:
    """r_a and r_b defined by structurally-identical lwz from r34+0x2C."""
    fd_a = FirstDef(block_idx=3, opcode="lwz", operands="r33,44(r34)",
                    annotations=[], regs=[("r", 33), ("r", 34)])
    fd_b = FirstDef(block_idx=5, opcode="lwz", operands="r35,44(r34)",
                    annotations=[], regs=[("r", 35), ("r", 34)])
    facts = _facts_with({
        33: _vf(33, fd_a),
        35: _vf(35, fd_b),
    })
    s = CommonSubExprPattern().check(facts, (33, 35))
    assert s is not None
    assert s.pattern_name == "common-subexpr"


def test_common_subexpr_skips_different_opcodes() -> None:
    """Same operands but `lwz` vs `lbz` → not the same expression."""
    fd_a = FirstDef(block_idx=3, opcode="lwz", operands="r33,44(r34)",
                    annotations=[], regs=[("r", 33), ("r", 34)])
    fd_b = FirstDef(block_idx=5, opcode="lbz", operands="r35,44(r34)",
                    annotations=[], regs=[("r", 35), ("r", 34)])
    facts = _facts_with({33: _vf(33, fd_a), 35: _vf(35, fd_b)})
    assert CommonSubExprPattern().check(facts, (33, 35)) is None


def test_common_subexpr_skips_different_operands() -> None:
    """Same opcode but different offsets → different expressions."""
    fd_a = FirstDef(block_idx=3, opcode="lwz", operands="r33,44(r34)",
                    annotations=[], regs=[("r", 33), ("r", 34)])
    fd_b = FirstDef(block_idx=5, opcode="lwz", operands="r35,48(r34)",
                    annotations=[], regs=[("r", 35), ("r", 34)])
    facts = _facts_with({33: _vf(33, fd_a), 35: _vf(35, fd_b)})
    assert CommonSubExprPattern().check(facts, (33, 35)) is None


def test_common_subexpr_skips_param_init() -> None:
    """Param-init ops in the entry block are NOT CSE candidates."""
    fd_a = FirstDef(block_idx=0, opcode="mr", operands="r33,r3",
                    annotations=[], regs=[("r", 33), ("r", 3)])
    fd_b = FirstDef(block_idx=0, opcode="mr", operands="r34,r3",
                    annotations=[], regs=[("r", 34), ("r", 3)])
    facts = _facts_with({
        33: _vf(33, fd_a, is_param=True),
        34: _vf(34, fd_b, is_param=True),
    })
    assert CommonSubExprPattern().check(facts, (33, 34)) is None
