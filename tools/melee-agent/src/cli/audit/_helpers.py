"""Audit commands - audit and recover tracked work."""

import asyncio
import json
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from .._common import (
    DEFAULT_MELEE_ROOT,
    console,
    db_upsert_function,
    load_completed_functions,
    save_completed_functions,
)
from src.mwcc_debug.source_patch import extract_function, replace_function

audit_app = typer.Typer(help="Audit and recover tracked work")


# ============================================================================
# Duplicate detection utilities
# ============================================================================

