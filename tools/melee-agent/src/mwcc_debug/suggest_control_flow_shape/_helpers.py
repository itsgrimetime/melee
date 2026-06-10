from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


_BOOL_CAST_OPS = {"subfic", "cntlzw", "srwi", "rlwinm"}
_COMPARE_OPS = {"cmpwi", "cmplwi", "cmpw", "cmplw"}
_CONDITIONAL_BRANCH_PREFIXES = (
    "bne",
    "beq",
    "blt",
    "bgt",
    "ble",
    "bge",
    "bdnz",
    "bdz",
)
_INDEXED_OPS = {
    "lbzx",
    "lhzx",
    "lwzx",
    "stbx",
    "sthx",
    "stwx",
    "lfsx",
    "stfsx",
}
_STRIDE_OPS = {"mulli", "slwi", "rlwinm"}
_CALL_OPS = {"bl", "bctrl"}
_LOOP_START_OPS = {"mtctr"}
_LOOP_END_OPS = {"bdnz", "bdz"}
_ARG_REGS = tuple(f"r{index}" for index in range(3, 11))
_VOLATILE_REGS = ("r0",) + tuple(f"r{index}" for index in range(3, 13))

_PRIORITY = {
    "branch-idiom": 10,
    "call-hoist": 20,
    "pointer-walk-indexed-shape": 30,
    "concurrent-buffer-lifetime": 35,
    "loop-peel-unroll": 40,
    "missing-extra-call-layer": 50,
}


@dataclass(frozen=True)
class _Instruction:
    index: int
    offset: int | None
    line: str
    opcode: str
    operands: str
    relocation_symbol: str | None = None


@dataclass(frozen=True)
class _LoopRegion:
    start: int
    end: int
    kind: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "start_index": self.start,
            "end_index": self.end,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class _StackHomeCall:
    call_index: int
    symbol: str
    offset: int
    line: str


