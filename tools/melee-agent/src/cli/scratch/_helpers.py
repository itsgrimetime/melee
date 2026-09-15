"""Scratch commands - manage decomp.me scratches.

This module handles all scratch operations: create, compile, update, get, search.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.table import Table

from .._common import (
    AGENT_ID,
    DECOMP_CONFIG_DIR,
    DEFAULT_MELEE_ROOT,
    console,
    db_record_match_score,
    db_upsert_function,
    db_upsert_scratch,
    detect_local_api_url,
    format_match_history,
    get_compiler_for_source,
    get_context_file,
    get_local_api_url,
    record_match_score,
    renew_claim_on_activity,
)
from ..complete import _get_current_branch
from ..utils import file_lock, load_json_safe

# Shared scratch tokens file - all agents use the same file
# Tokens are keyed by scratch slug, so no conflicts between agents
DECOMP_SCRATCH_TOKENS_FILE = os.environ.get(
    "DECOMP_SCRATCH_TOKENS_FILE", str(DECOMP_CONFIG_DIR / "scratch_tokens.json")
)

# Lock file for token operations
_TOKENS_LOCK_FILE = DECOMP_CONFIG_DIR / "scratch_tokens.lock"

# Context file override from environment
_context_env = os.environ.get("DECOMP_CONTEXT_FILE", "")

