"""Explain observed scheduler windows for force-schedule targets."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace

from ..asm_windows import (
    AsmWindowCandidate,
    AsmWindowResult,
    explain_code_offset_window,
    is_memory_load_opcode,
)
from ..parser import Function, Instruction, Pass, parse_pcdump


