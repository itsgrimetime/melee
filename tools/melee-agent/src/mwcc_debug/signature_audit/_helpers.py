"""Audit checkdiff call-prep signature/type mismatches against source calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..cast_audit import (
    _extract_local_types,
    _is_float_type,
    _is_integer_type,
    _looks_integer,
    _split_args,
    find_call_sites,
)
from ..source_patch import find_function

__all__ = [name for name in globals() if not name.startswith("__")]
