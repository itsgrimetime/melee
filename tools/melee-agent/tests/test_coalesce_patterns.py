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
