"""
Opcode sequence synthesis - generate C samples to build an opcode pattern database.

This module generates variations of C code snippets, compiles them with mwcc,
and indexes the resulting opcode sequences for pattern matching.
"""

from .compiler import Compiler, CompileResult
from .contexts import ALL_CONTEXTS, AdvancedContext, MinimalContext
from .opcodes import OpcodeSequence, extract_opcodes, normalize_instruction
from .parallel import ParallelCompiler, bulk_generate
from .storage import OpcodeDB
from .templates import ALL_TEMPLATES as BASIC_TEMPLATES
from .templates import Template
from .templates_advanced import ADVANCED_TEMPLATES

# Combined templates for full generation
ALL_TEMPLATES = BASIC_TEMPLATES + ADVANCED_TEMPLATES

__all__ = [
    "Template",
    "BASIC_TEMPLATES",
    "ADVANCED_TEMPLATES",
    "ALL_TEMPLATES",
    "ALL_CONTEXTS",
    "MinimalContext",
    "AdvancedContext",
    "Compiler",
    "CompileResult",
    "ParallelCompiler",
    "bulk_generate",
    "OpcodeDB",
    "OpcodeSequence",
    "extract_opcodes",
    "normalize_instruction",
]
