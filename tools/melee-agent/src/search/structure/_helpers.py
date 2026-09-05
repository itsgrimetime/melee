"""Result models and payload helpers for structure search."""

from __future__ import annotations

import difflib
import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from src.mwcc_debug.source_patch import (
    find_function,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
)

DEFAULT_STRUCTURE_AXES = (
    "decl-order",
    "control-flow",
    "case-order",
    "statement-order",
)
OPTIONAL_STRUCTURE_AXES = (
    "source-lifetime",
    "inline-boundary",
    "loop-shape-expanded",
)
SUPPORTED_STRUCTURE_AXES = (
    *DEFAULT_STRUCTURE_AXES,
    *OPTIONAL_STRUCTURE_AXES,
)
SCORE_CAP_UNSCORED_REASON = "not scored due max-candidates cap"
_INLINE_BOUNDARY_CALL_RESULT_RETURNS = {
    "GetNameText": "char*",
    "GetPersistentNameData": "struct NameTagData*",
    "GetPersistentFighterData": "struct FighterData*",
    "mnDiagram_GetFighterByIndex": "u8",
}

__all__ = [name for name in globals() if not name.startswith("__")]
