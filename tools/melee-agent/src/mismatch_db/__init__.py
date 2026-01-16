"""
Mismatch Pattern Database

A searchable database of patterns discovered during decompilation matching.
"""

from .models import (
    Example,
    Fix,
    Pattern,
    PatternDB,
    Provenance,
    ProvenanceEntry,
    Signal,
)
from .schema import CATEGORIES, DEFAULT_DB_PATH, SIGNAL_TYPES, get_db, init_db

__all__ = [
    "init_db",
    "get_db",
    "SIGNAL_TYPES",
    "CATEGORIES",
    "DEFAULT_DB_PATH",
    "Pattern",
    "Signal",
    "Example",
    "Fix",
    "Provenance",
    "ProvenanceEntry",
    "PatternDB",
]
