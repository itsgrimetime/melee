"""Parsing and analysis utilities for mwcc_debug pcdump.txt output."""

from .parser import (
    Function,
    Instruction,
    Pass,
    VirtualRegInfo,
    analyze_function,
    parse_pcdump,
)
from .simulator import (
    SimDecision,
    simulate_function,
)

__all__ = [
    "Function",
    "Instruction",
    "Pass",
    "SimDecision",
    "VirtualRegInfo",
    "analyze_function",
    "parse_pcdump",
    "simulate_function",
]
