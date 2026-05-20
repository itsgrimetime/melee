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
