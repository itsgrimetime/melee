"""Targeted diagnostics for final-only stack-home mismatches."""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict
from typing import Any

from ..stack_slot_bridge import explain_stack_slot_localizer
from ..virtual_attribution import explain_virtuals


_ASM_STACK_SLOT_RE = re.compile(r"(?P<offset>-?(?:0x[0-9A-Fa-f]+|\d+))\(r1\)")
_ASM_BRANCH_CALL_RE = re.compile(r"\bbl\s+(?P<call>[A-Za-z_]\w*)")
_ASM_RELOC_CALL_RE = re.compile(r"\bR_PPC_REL24\s+(?P<call>[A-Za-z_]\w*)")


