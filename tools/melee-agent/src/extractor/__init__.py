"""Function extractor module for the melee decompilation project.

This module extracts unmatched functions from the melee decompilation project,
including their assembly code, context, and match status.
"""

from .asm import AsmExtractor, extract_asm_for_function
from .context import ContextGenerator, generate_context
from .extractor import (
    FunctionExtractor,
    extract_function,
    extract_unmatched_functions,
)
from .models import (
    ExtractionResult,
    FunctionInfo,
    FunctionMatch,
    FunctionSymbol,
    ObjectStatus,
)
from .parser import ConfigureParser, parse_configure
from .report import ReportParser, parse_report
from .splits import SplitsParser, parse_splits
from .symbols import SymbolParser, parse_symbols

__all__ = [
    # Models
    "ObjectStatus",
    "FunctionSymbol",
    "FunctionMatch",
    "FunctionInfo",
    "ExtractionResult",
    # Parsers and extractors
    "ConfigureParser",
    "ReportParser",
    "ContextGenerator",
    "SymbolParser",
    "AsmExtractor",
    "SplitsParser",
    "FunctionExtractor",
    # Async functions
    "parse_configure",
    "parse_report",
    "generate_context",
    "parse_symbols",
    "parse_splits",
    "extract_asm_for_function",
    "extract_unmatched_functions",
    "extract_function",
]

__version__ = "0.1.0"
