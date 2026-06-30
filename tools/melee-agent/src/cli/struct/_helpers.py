"""Struct commands - lookup struct layouts, field offsets, and callback signatures."""

import asyncio
import inspect
import json as _json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from .._common import console, get_agent_melee_root, get_local_api_url

struct_app = typer.Typer(help="Lookup struct layouts and field offsets")

# Known type issues in the headers that cause matching problems
# Format: (struct, field, declared_type, actual_type, notes)
KNOWN_TYPE_ISSUES = [
    ("Fighter.dmg", "x1894", "int", "HSD_GObj*", "Source gobj pointer, loaded with lwz then dereferenced"),
    ("Fighter.dmg", "x1898", "int", "float", "Damage rate, loaded with lfs instruction"),
    ("Fighter.dmg", "x1880", "int", "Vec3*", "Effect position pointer"),
    ("Item", "xD90", "union Struct2070", "union Struct2070", "Same as Fighter.x2070, access via xD90.x2073"),
]

# Common struct locations
STRUCT_FILES = {
    "Fighter": "src/melee/ft/types.h",
    "Item": "src/melee/it/types.h",
    "HSD_GObj": "src/sysdolphin/baselib/gobj.h",
    "ftCo_DatAttrs": "src/melee/ft/types.h",
    "CollData": "src/melee/lb/types.h",
}

