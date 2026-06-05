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
from .guidance import (
    Suggestion,
    format_suggestions,
    suggest,
)
from .patterns import (
    PATTERNS,
    MutationPattern,
    get_pattern,
    list_patterns,
    patterns_for_category,
)
from .parser import (
    Function,
    Instruction,
    Pass,
    VirtualRegInfo,
    analyze_function,
    parse_pcdump,
)
from .scoring import (
    ScoreBreakdown,
    ScoreWeights,
    derive_target_from_function,
    score_function,
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
    "MutationPattern",
    "PATTERNS",
    "Pass",
    "ScoreBreakdown",
    "ScoreWeights",
    "SimDecision",
    "SimplifyEntry",
    "SimplifySection",
    "Suggestion",
    "VirtualRegInfo",
    "analyze_function",
    "derive_target_from_function",
    "find_function",
    "format_suggestions",
    "get_pattern",
    "list_patterns",
    "parse_hook_events",
    "parse_pcdump",
    "patterns_for_category",
    "score_function",
    "simulate_function",
    "suggest",
]
