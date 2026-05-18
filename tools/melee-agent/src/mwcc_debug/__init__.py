"""Parsing and analysis utilities for mwcc_debug pcdump.txt output."""

from .colorgraph_parser import (
    ColorgraphDecision,
    ColorgraphSection,
    ConstPropEvent,
    FunctionEvents,
    IGConstructedEvent,
    SimplifyEntry,
    SimplifySection,
    find_function,
    parse_hook_events,
)
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
    "ColorgraphDecision",
    "ColorgraphSection",
    "ConstPropEvent",
    "Function",
    "FunctionEvents",
    "IGConstructedEvent",
    "Instruction",
    "Pass",
    "SimDecision",
    "SimplifyEntry",
    "SimplifySection",
    "VirtualRegInfo",
    "analyze_function",
    "find_function",
    "parse_hook_events",
    "parse_pcdump",
    "simulate_function",
]
