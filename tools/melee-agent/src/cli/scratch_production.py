"""Production scratch creation from a worktree function.

Implements ``melee-agent scratch create <func> --production``: build a scratch
payload directly from the worktree (no local decomp.me server) and create it on
https://decomp.me using stored production credentials.
"""

import asyncio
from pathlib import Path

import httpx
import typer

from ._common import (
    PRODUCTION_DECOMP_ME,
    console,
    db_upsert_function,
    db_upsert_scratch,
    get_compiler_for_source,
)
from .sync._helpers import create_and_claim_production_scratch, load_production_cookies
from .sync.auth import get_production_user_agent

# Matches the local `scratch create` default. Diverges from CLAUDE.md canonical
# (-fp hard not -fp hardware, no -proc gekko); reused for parity with local
# create since there is no source scratch to copy flags from.
PRODUCTION_COMPILER_FLAGS = (
    "-O4,p -nodefaults -fp hard -Cpp_exceptions off -enum int -fp_contract on -inline auto"
)


def build_production_create_data(
    *,
    name: str,
    target_asm: str,
    context: str,
    source_code: str,
    compiler: str,
    flags: str = PRODUCTION_COMPILER_FLAGS,
) -> dict:
    """Build the /api/scratch POST body for a production scratch (pure)."""
    return {
        "name": name,
        "target_asm": target_asm,
        "context": context,
        "compiler": compiler,
        "compiler_flags": flags,
        "diff_label": name,
        "source_code": source_code,
        "platform": "gc_wii",
        "diff_flags": [],
    }


def _seed_source_from_repo(name: str, file_path: str, melee_root: Path) -> str:
    """Return the function's current C from src/, or a stub if not found."""
    from src.commit.update import _extract_function_from_code

    src_path = melee_root / "src" / file_path
    if src_path.exists():
        extracted = _extract_function_from_code(src_path.read_text(encoding="utf-8"), name)
        if extracted:
            return extracted
    return "// TODO: Decompile this function\n"
