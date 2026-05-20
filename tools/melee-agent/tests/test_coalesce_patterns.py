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
