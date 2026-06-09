"""CLI for the search substrate: `melee-agent debug search run`.

Register under debug_app via: debug_app.add_typer(search_app, name="search")
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from itertools import combinations
from pathlib import Path
from typing import Annotated, Optional

import typer

from src.search.structure import (
    DEFAULT_STRUCTURE_AXES,
    SUPPORTED_STRUCTURE_AXES,
    render_structure_text,
    run_structure_search,
)
from src.search.structure_scoring import score_structure_variants

search_app = typer.Typer(
    help="Fast+directed match-search substrate (Spec 1).",
    no_args_is_help=True,
)

# Canonical mwcc cflags used by the project (see CLAUDE.md "Notes").
_CFLAGS = (
    "-O4,p -nodefaults -proc gekko -fp hardware -Cpp_exceptions off "
    "-enum int -fp_contract on -inline auto"
)

