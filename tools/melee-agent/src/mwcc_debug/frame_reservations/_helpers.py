"""Diagnose implicit stack frame reservation ranges from pcdump/asm."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..parser import Function, Instruction, Pass, parse_pcdump


_FRAME_RE = re.compile(
    r"\br1\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)"
)
_STACK_REF_RE = re.compile(
    r"(?<![@\w+])(?P<offset>-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)"
)
_SYMBOLIC_STACK_REF_RE = re.compile(
    r"(?<![@\w])(?P<symbol>(?:@[A-Za-z0-9_]\w*|[A-Za-z_]\w*)"
    r"(?:[+-](?:0x[0-9A-Fa-f]+|\d+))?)\s*\(\s*r1\s*\)"
)
_REG_OPERAND_RE = re.compile(r"\b(?P<class>[rf])(?P<num>\d+)\b")
_ASM_COMMENT_RE = re.compile(r"^\s*/\*.*?\*/\s*")
_ASM_OFFSET_BYTES_RE = re.compile(
    r"^\s*[+-]?[0-9A-Fa-f]+:\s+(?:(?:[0-9A-Fa-f]{2})\s+)*"
)

