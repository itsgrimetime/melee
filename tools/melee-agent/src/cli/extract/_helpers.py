"""Extract commands - list and extract unmatched functions."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table

from .._common import (
    AGENT_ID,
    DEFAULT_MELEE_ROOT,
    console,
    db_upsert_function,
    db_upsert_scratch,
    detect_local_api_url,
    get_compiler_for_source,
    get_context_file,
    resolve_melee_root,
)

# Try to import tree-sitter based functions for better accuracy
try:
    from src.hooks.c_analyzer import (
        TREE_SITTER_AVAILABLE,
    )
    from src.hooks.c_analyzer import (
        strip_function_bodies as _ts_strip_function_bodies,
    )
    from src.hooks.c_analyzer import (
        strip_target_function as _ts_strip_target_function,
    )
except ImportError:
    TREE_SITTER_AVAILABLE = False
    _ts_strip_function_bodies = None
    _ts_strip_target_function = None

# Context file override from environment
_context_env = os.environ.get("DECOMP_CONTEXT_FILE", "")

