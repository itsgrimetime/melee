#!/usr/bin/env python3
"""
Helper script for LLM-driven decompiling. Fixes any missing imports, then
rebuilds and runs objdiff-cli on the specified function.

Usage:
  tools/checkdiff.py <function_name>
  tools/checkdiff.py <function_name> --no-tty  # Force non-interactive mode

Automatically uses non-interactive mode when no TTY is detected (e.g., agents).

Remote environment support:
  - Auto-downloads dtk (decomp-toolkit) if powerpc-eabi-objdump is not available
  - Works in containers without devkitPPC installed
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent

# sys.path shim so `src.cli.*` imports resolve. checkdiff.py lives
# outside the melee-agent package; we add the parent of ``src/`` so the
# package is discoverable. The existing in-function shim inside
# apply_name_magic_if_available adds ``melee-agent/src`` directly (for
# ``from mwcc_debug...`` imports of subpackages), so both are needed.
_MELEE_AGENT_ROOT = SCRIPT_DIR / "melee-agent"
_MELEE_AGENT_SRC = _MELEE_AGENT_ROOT / "src"
if _MELEE_AGENT_ROOT.exists():
    _melee_root_str = str(_MELEE_AGENT_ROOT)
    if _melee_root_str not in sys.path:
        sys.path.insert(0, _melee_root_str)
if _MELEE_AGENT_SRC.exists():
    _melee_src_str = str(_MELEE_AGENT_SRC)
    if _melee_src_str not in sys.path:
        sys.path.insert(0, _melee_src_str)

try:
    from src.cli.fingerprint import (
        extract_function_body,
        fingerprint_for,
        Fingerprint,
    )
    from src.cli.tracking import (
        find_attempt_by_fp,
        increment_replay,
        record_attempt,
    )
    _FINGERPRINT_AVAILABLE = True
except ImportError:
    _FINGERPRINT_AVAILABLE = False
    Fingerprint = None  # type: ignore
    extract_function_body = None  # type: ignore

try:
    from src.mwcc_debug.stack_slot_bridge import (
        explain_stack_slot_localizer,
        render_stack_slot_bridge_summary,
    )
except ImportError:
    explain_stack_slot_localizer = None  # type: ignore
    render_stack_slot_bridge_summary = None  # type: ignore

try:
    from src.mwcc_debug.value_numbering import (
        detect_divide_rematerialization_ceiling,
    )
except ImportError:
    detect_divide_rematerialization_ceiling = None  # type: ignore


def _is_repo_root(path: Path) -> bool:
    return (
        (path / "configure.py").is_file()
        and (path / "src").is_dir()
        and (path / "config/GALE01").is_dir()
    )


def _find_cwd_repo_root() -> Optional[Path]:
    cwd = Path.cwd().resolve()
    for path in (cwd, *cwd.parents):
        if _is_repo_root(path):
            return path
    return None


ROOT = _find_cwd_repo_root() or SCRIPT_DIR.parent  # tools/ is in repo root

REPORT_PATH = ROOT / "build/GALE01/report.json"
OBJDIFF_CONFIG_PATH = ROOT / "objdiff.json"
SRC_ROOT = ROOT / "src"
DEFAULT_BUILD_TIMEOUT_SECONDS = int(os.environ.get("CHECKDIFF_BUILD_TIMEOUT", "300"))
REPORT_JSON_READ_RETRIES = int(os.environ.get("CHECKDIFF_REPORT_JSON_READ_RETRIES", "5"))
REPORT_JSON_READ_RETRY_DELAY_SECONDS = float(
    os.environ.get("CHECKDIFF_REPORT_JSON_READ_RETRY_DELAY", "0.05")
)
EXPECTED_WORKTREE_ENV_VARS = ("MELEE_AGENT_EXPECTED_WORKTREE", "GIT_WORK_TREE")

# Tool paths
TOOLS_CACHE_DIR = Path.home() / ".cache" / "melee-tools"
DTK_VERSION = "v1.8.0"

# Use our bundled objdiff-cli if available
OBJDIFF_CLI = SCRIPT_DIR / "objdiff-cli"
if not OBJDIFF_CLI.exists():
    OBJDIFF_CLI = "objdiff-cli"  # Fall back to PATH


def format_subprocess_failure(
    headline: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    """Format subprocess failure context for warnings that continue."""
    command = " ".join(str(part) for part in result.args)
    cause = (result.stderr or result.stdout or "").strip()
    lines = [
        headline,
        f"  command: {command}",
        f"  exit code: {result.returncode}",
    ]
    if cause:
        lines.append(f"  output: {cause}")
    return "\n".join(lines)


def _timeout_completed_process(
    args: list[str],
    *,
    timeout: float,
    hint: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args,
        124,
        "",
        f"timed out after {timeout:g}s running {' '.join(args)}; {hint}",
    )


def _run_build_command(
    args: list[str],
    *,
    timeout: float,
    hint: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _timeout_completed_process(args, timeout=timeout, hint=hint)


def _resolve_expected_worktree(raw_path: str) -> Path:
    path = Path(os.path.expandvars(raw_path)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def expected_worktree_guard_error() -> str | None:
    current_root = ROOT.resolve()
    for env_name in EXPECTED_WORKTREE_ENV_VARS:
        raw_path = os.environ.get(env_name)
        if not raw_path:
            continue
        expected_root = _resolve_expected_worktree(raw_path)
        if expected_root == current_root:
            continue
        return (
            "[checkdiff] refusing to run from repo root "
            f"{current_root} because {env_name} points to {expected_root}. "
            "Run checkdiff from the isolated worktree, or unset the expected "
            "worktree environment after confirming this is intentional."
        )
    return None


def get_dtk_download_url() -> str:
    """Get the appropriate dtk download URL for this platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-linux-x86_64"
        elif machine in ("aarch64", "arm64"):
            return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-linux-aarch64"
        elif machine in ("i686", "i386"):
            return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-linux-i686"
    elif system == "darwin":
        if machine in ("x86_64", "amd64"):
            return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-macos-x86_64"
        elif machine in ("aarch64", "arm64"):
            # The native macOS arm64 DTK binary can launch-suspend indefinitely
            # on some Apple Silicon hosts. Rosetta x86_64 DTK is slower to
            # launch but reliable.
            return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-macos-x86_64"
    elif system == "windows":
        return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-windows-x86_64.exe"

    raise RuntimeError(f"Unsupported platform: {system} {machine}")


def download_dtk(dest: Path) -> Path:
    """Download dtk binary to the specified path."""
    url = get_dtk_download_url()
    dest.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading dtk from {url}...", file=sys.stderr)
    try:
        urllib.request.urlretrieve(url, dest)
        dest.chmod(0o755)
        print(f"Downloaded dtk to {dest}", file=sys.stderr)
        return dest
    except Exception as e:
        raise RuntimeError(f"Failed to download dtk: {e}")


def find_objdump() -> Optional[Path]:
    """Find powerpc-eabi-objdump in standard locations."""
    candidates = [
        Path("/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump"),
        Path.home() / "devkitPro" / "devkitPPC" / "bin" / "powerpc-eabi-objdump",
    ]

    # Check environment variable
    if env_path := os.environ.get("PPC_EABI_OBJDUMP"):
        candidates.insert(0, Path(env_path))

    # Check PATH
    if objdump_path := shutil.which("powerpc-eabi-objdump"):
        candidates.insert(0, Path(objdump_path))

    for path in candidates:
        if path.exists() and os.access(path, os.X_OK):
            return path

    return None


def find_dtk() -> Optional[Path]:
    """Find dtk in standard locations or cache."""
    candidates = [
        SCRIPT_DIR / "dtk",
        ROOT / "build" / "tools" / "dtk",
        TOOLS_CACHE_DIR / "dtk",
    ]

    # Check PATH
    if dtk_path := shutil.which("dtk"):
        candidates.insert(0, Path(dtk_path))

    for path in candidates:
        if path.exists() and os.access(path, os.X_OK):
            return path

    return None


def ensure_disassembler() -> tuple[str, Path]:
    """
    Ensure a disassembler is available, downloading if necessary.

    Returns:
        Tuple of (disassembler_type, path) where type is 'objdump' or 'dtk'
    """
    # Prefer objdump if available (faster, more common)
    if objdump := find_objdump():
        return ("objdump", objdump)

    # Try dtk
    if dtk := find_dtk():
        return ("dtk", dtk)

    # Download dtk as fallback
    dtk_path = TOOLS_CACHE_DIR / "dtk"
    download_dtk(dtk_path)
    return ("dtk", dtk_path)


def apply_name_magic_if_available(
    source_o: Path,
    target_o: Path,
    *,
    verbose: bool = False,
) -> Optional[dict]:
    """Auto-rename anonymous .sdata2 magic constants in ``source_o`` using
    named symbols from ``target_o``.

    MWCC emits int-to-float bias literals as anonymous ``@N`` symbols in
    ``.sdata2``. The production .o references the same bytes via named
    globals (e.g. ``mnVibration_804DC018``). objdiff reports a relocation-
    name mismatch even though the function body is otherwise identical.
    This helper resolves that by renaming the anonymous symbols in place
    via objcopy.

    Idempotent: calling repeatedly on the same ``source_o`` is a no-op
    after the first invocation (no @N symbols remain to rename).

    Returns ``None`` (silently) when:
        - ``target_o`` does not exist,
        - the ``melee-agent`` helper module is unavailable, or
        - objcopy is missing or fails.

    Returns a dict ``{"renames": [...], "globalized": [...],
    "unresolved": [...]}`` on success. The dict's lists may be empty if
    the .o has no anonymous magic constants to rename.
    """
    if not target_o.exists():
        return None
    melee_agent_src = SCRIPT_DIR / "melee-agent" / "src"
    if not melee_agent_src.is_dir():
        return None
    _path_str = str(melee_agent_src)
    _added_path = _path_str not in sys.path
    if _added_path:
        sys.path.insert(0, _path_str)
    try:
        from mwcc_debug.o_rewriter import apply_name_magic_auto
    except ImportError:
        return None
    finally:
        if _added_path and sys.path and sys.path[0] == _path_str:
            sys.path.pop(0)

    try:
        result = apply_name_magic_auto(source_o, target_o)
    except (FileNotFoundError, ImportError, subprocess.CalledProcessError, OSError) as exc:
        if verbose:
            print(
                f"warning: name-magic auto-rename skipped: {exc}",
                file=sys.stderr,
            )
        return None

    summary = {
        "renames": list(result.renames),
        "globalized": list(result.globalized),
        "unresolved": [s.name for s in result.unresolved],
    }
    if verbose and summary["renames"]:
        print(
            f"[checkdiff] name-magic: renamed {len(summary['renames'])} "
            f"anonymous .sdata2 symbol(s) via {target_o}",
            file=sys.stderr,
        )
        for old, new in summary["renames"]:
            print(f"           {old} -> {new}", file=sys.stderr)
    return summary


def checkdiff_lock_path(obj_path: str | None = None) -> Path:
    """Return the repo-wide lock path for compile-producing checkdiff work."""
    lock_dir = Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    digest = hashlib.sha1(str(ROOT.resolve()).encode()).hexdigest()[:12]
    return lock_dir / f"repo.{digest}.lock"


def acquire_checkdiff_lock(obj_path: str):
    """Acquire a repo-wide lock for compile/report-producing checkdiff work."""
    if os.environ.get("CHECKDIFF_NO_LOCK"):
        return None

    try:
        import fcntl
    except ImportError:
        return None

    lock_dir = Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = checkdiff_lock_path(obj_path)
    lock_file = lock_path.open("w")

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("waiting for repo-wide checkdiff build/report lock", file=sys.stderr)
        start = time.monotonic()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elapsed = time.monotonic() - start
        print(f"acquired checkdiff lock after {elapsed:.1f}s", file=sys.stderr)

    return lock_file


def should_acquire_checkdiff_lock(args) -> bool:
    """Return whether this checkdiff invocation mutates build/report state."""
    return not getattr(args, "no_build", False)


def _asm_body(line: str) -> str:
    if line.startswith("<"):
        return line
    if ":" in line:
        line = line.split(":", 1)[1]
    line = line.strip()
    line = re.sub(r"^(?:[0-9a-fA-F]{2}\s+){4}", "", line)
    line = re.sub(r"^[0-9a-fA-F]{8}\s+", "", line)
    return line.strip()


def _is_relocation_line(line: str) -> bool:
    body = _asm_body(line)
    return (
        "R_PPC_" in body
        or body.startswith(".reloc")
        or "\t.reloc" in body
    )


def _strip_relocation_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if not _is_relocation_line(line)]


_TRUTH_REGISTER_TOKEN_RE = re.compile(r"\b[rf](?:[0-9]|[12][0-9]|3[01])\b")
_TRUTH_CR_TOKEN_RE = re.compile(r"\bcr[0-7]\b")
_TRUTH_QUOTED_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
_TRUTH_SYMBOL_RE = re.compile(
    r"\b(?:[A-Za-z_][A-Za-z0-9_$]*_)[A-Za-z0-9_$.]*"
    r"(?:[+-](?:0x)?[0-9A-Fa-f]+)?\b"
)
_TRUTH_IMMEDIATE_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?(?:0x[0-9A-Fa-f]+|\d+)(?![A-Za-z_])"
)


def _normalized_truth_line(line: str) -> str | None:
    body = _asm_body(line)
    if not body or body.startswith("<"):
        return None
    body = _TRUTH_QUOTED_STRING_RE.sub('"STR"', body)
    if _is_relocation_line(line):
        reloc = re.search(r"R_PPC_[A-Za-z0-9_]+", body)
        return f"RELOC {reloc.group(0) if reloc else 'R_PPC'}"
    body = re.sub(r"<[^>]*>", "LABEL", body)
    body = _TRUTH_SYMBOL_RE.sub("SYM", body)
    body = _TRUTH_REGISTER_TOKEN_RE.sub(lambda m: f"{m.group(0)[0]}N", body)
    body = _TRUTH_CR_TOKEN_RE.sub("crN", body)
    body = _TRUTH_IMMEDIATE_RE.sub("IMM", body)
    return re.sub(r"\s+", " ", body).strip()


def normalized_structural_lines(lines: list[str]) -> list[str]:
    return [
        normalized
        for line in lines
        if (normalized := _normalized_truth_line(line)) is not None
    ]


def normalized_structural_diff(ref_lines: list[str], our_lines: list[str]) -> dict:
    ref_norm = normalized_structural_lines(ref_lines)
    our_norm = normalized_structural_lines(our_lines)
    sm = difflib.SequenceMatcher(None, ref_norm, our_norm, autojunk=False)
    diff_lines = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
        if tag != "equal"
    )
    if diff_lines == 0:
        status = "structural-match"
    elif diff_lines <= 3:
        status = "near-zero-structural-diff"
    else:
        status = "structural-diff"
    return {
        "status": status,
        "normalized_diff_lines": diff_lines,
        "expected_normalized_lines": len(ref_norm),
        "current_normalized_lines": len(our_norm),
    }


# Matches the normalized offset prefix produced by get_asm_with_objdump/dtk,
# e.g. "+0c0: " or "+042: ". The offset is hex, variable-width (3+ digits).
_NORMALIZED_OFFSET_RE = re.compile(r"^\+([0-9a-fA-F]+):(\s)")
_SECTION_ANCHOR_NAME_RE = re.compile(r"^\.\.\.[A-Za-z0-9_$.]+\.\d+$")
_BSS_ANCHOR_NAME_RE = re.compile(
    r"^\.\.\.bss\.\d+(?:[+-](?:0x)?[0-9A-Fa-f]+)?$"
)
_ANONYMOUS_DATA_SYMBOL_RE = re.compile(r"^@\d+$")
_SECTION_ANCHOR_TOKEN_CHARS = r"A-Za-z0-9_$."
_ANONYMOUS_DATA_ALIAS_SECTIONS = {".data", ".sdata"}
_RELOCATION_REFERENCE_RE = re.compile(
    r"^(?P<kind>R_PPC_[A-Za-z0-9_]+)\s+(?P<symbol>\S+)$"
)
_DOT_RELOCATION_REFERENCE_RE = re.compile(
    r"^\.reloc\s+[^,]+,\s*(?P<kind>R_PPC_[A-Za-z0-9_]+)\s*,\s*"
    r"(?P<symbol>\S+)$"
)
_SYMBOL_ADDEND_RE = re.compile(
    r"^(?P<base>.+?)(?P<addend>[+-](?:0x)?[0-9A-Fa-f]+)?$"
)
_NAMED_OBJECT_SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$.]*$")


def _is_section_anchor_symbol(name: str) -> bool:
    return bool(_SECTION_ANCHOR_NAME_RE.match(name))


def _is_bss_anchor_symbol(name: str) -> bool:
    return bool(_BSS_ANCHOR_NAME_RE.match(name))


def _split_symbol_addend(name: str) -> tuple[str, str]:
    match = _SYMBOL_ADDEND_RE.match(name)
    if match is None:
        return name, ""
    return match.group("base"), match.group("addend") or ""


def _is_named_object_symbol(name: str) -> bool:
    base, _addend = _split_symbol_addend(name)
    if base.startswith(("@", ".", "...")):
        return False
    return bool(_NAMED_OBJECT_SYMBOL_RE.match(base))


def _parse_relocation_reference(line: str) -> dict[str, str] | None:
    if not _is_relocation_line(line):
        return None
    offset_match = _NORMALIZED_OFFSET_RE.match(line)
    if offset_match is None:
        return None
    body = _asm_body(line)
    match = _RELOCATION_REFERENCE_RE.match(body)
    if match is None:
        match = _DOT_RELOCATION_REFERENCE_RE.match(body)
    if match is None:
        return None
    return {
        "offset": offset_match.group(1).lower(),
        "kind": match.group("kind"),
        "symbol": match.group("symbol"),
    }


def _bss_anchor_pair(
    ref: dict[str, str],
    current: dict[str, str],
) -> dict[str, str] | None:
    if ref["offset"] != current["offset"] or ref["kind"] != current["kind"]:
        return None

    ref_symbol = ref["symbol"]
    current_symbol = current["symbol"]
    if _is_named_object_symbol(ref_symbol) and _is_bss_anchor_symbol(current_symbol):
        named_symbol, named_addend = _split_symbol_addend(ref_symbol)
        anchor_symbol, anchor_addend = _split_symbol_addend(current_symbol)
        pair = {
            "offset": ref["offset"],
            "kind": ref["kind"],
            "named_symbol": named_symbol,
            "anchor_symbol": anchor_symbol,
            "named_side": "expected",
        }
    elif _is_bss_anchor_symbol(ref_symbol) and _is_named_object_symbol(current_symbol):
        anchor_symbol, anchor_addend = _split_symbol_addend(ref_symbol)
        named_symbol, named_addend = _split_symbol_addend(current_symbol)
        pair = {
            "offset": ref["offset"],
            "kind": ref["kind"],
            "named_symbol": named_symbol,
            "anchor_symbol": anchor_symbol,
            "named_side": "current",
        }
    else:
        return None

    if named_addend:
        pair["named_addend"] = named_addend
    if anchor_addend:
        pair["anchor_addend"] = anchor_addend
    return pair


def detect_bss_anchor_relocations(
    ref_lines: list[str],
    our_lines: list[str],
) -> dict[str, object] | None:
    """Find named-BSS versus ``...bss.N`` relocation residuals."""
    ref_relocations = [
        parsed
        for line in ref_lines
        if (parsed := _parse_relocation_reference(line)) is not None
    ]
    current_relocations = [
        parsed
        for line in our_lines
        if (parsed := _parse_relocation_reference(line)) is not None
    ]
    used_current: set[int] = set()
    pairs: list[dict[str, str]] = []
    for ref in ref_relocations:
        for index, current in enumerate(current_relocations):
            if index in used_current:
                continue
            pair = _bss_anchor_pair(ref, current)
            if pair is None:
                continue
            used_current.add(index)
            pairs.append(pair)
            break

    if not pairs:
        return None
    return {"status": "ceiling", "pairs": pairs}


def _format_bss_anchor_relocation_diagnostic(diagnostic: dict[str, object]) -> str:
    pairs = diagnostic.get("pairs")
    if not isinstance(pairs, list):
        return "BSS section-anchor ceiling"
    seen: set[tuple[str, str]] = set()
    parts: list[str] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        named = str(pair.get("named_symbol") or "")
        anchor = str(pair.get("anchor_symbol") or "")
        key = (named, anchor)
        if not named or not anchor or key in seen:
            continue
        seen.add(key)
        parts.append(f"{named} vs {anchor}")
    if not parts:
        return "BSS section-anchor ceiling"
    return "BSS section-anchor ceiling: " + ", ".join(parts)


def _is_anonymous_data_symbol(name: str) -> bool:
    return bool(_ANONYMOUS_DATA_SYMBOL_RE.match(name))


def _collect_symbol_aliases_by_location(
    symbols: list[dict[str, object]],
    *,
    peer_symbols: list[dict[str, object]] | None = None,
) -> dict[str, str]:
    anchors_by_loc: dict[tuple[int, int], list[str]] = {}
    anonymous_by_loc: dict[tuple[int, int], list[str]] = {}
    globals_by_loc: dict[tuple[int, int], list[str]] = {}
    anonymous_records: list[dict[str, object]] = []
    global_records: list[dict[str, object]] = []

    for sym in symbols:
        name = sym["name"]
        shndx = sym["shndx"]
        if not isinstance(name, str) or not name or not isinstance(shndx, int):
            continue

        loc = (shndx, int(sym["value"]))
        bind = sym["bind"]
        sym_type = sym["type"]
        size = int(sym["size"])
        section = sym["section"]

        if (
            bind == "STB_LOCAL"
            and size == 0
            and _is_section_anchor_symbol(name)
            and not _is_bss_anchor_symbol(name)
        ):
            anchors_by_loc.setdefault(loc, []).append(name)
        elif (
            bind == "STB_LOCAL"
            and sym_type == "STT_OBJECT"
            and isinstance(section, str)
            and section in _ANONYMOUS_DATA_ALIAS_SECTIONS
            and _is_anonymous_data_symbol(name)
        ):
            anonymous_by_loc.setdefault(loc, []).append(name)
            anonymous_records.append(sym)
        elif (
            bind == "STB_GLOBAL"
            and sym_type == "STT_OBJECT"
            and size > 0
            and not name.startswith("gap_")
            and not _is_section_anchor_symbol(name)
            and not _is_anonymous_data_symbol(name)
        ):
            globals_by_loc.setdefault(loc, []).append(name)
            global_records.append(sym)

    if peer_symbols is not None:
        for sym in peer_symbols:
            name = sym["name"]
            section = sym["section"]
            if not isinstance(name, str) or not isinstance(section, str):
                continue
            if (
                sym["bind"] == "STB_GLOBAL"
                and sym["type"] == "STT_OBJECT"
                and int(sym["size"]) > 0
                and section in _ANONYMOUS_DATA_ALIAS_SECTIONS
                and not name.startswith("gap_")
                and not _is_section_anchor_symbol(name)
                and not _is_anonymous_data_symbol(name)
            ):
                global_records.append(sym)

    aliases: dict[str, str] = {}
    for local_by_loc in (anchors_by_loc, anonymous_by_loc):
        for loc, local_names in local_by_loc.items():
            globals_at_loc = globals_by_loc.get(loc)
            if not globals_at_loc:
                continue
            replacement = sorted(globals_at_loc)[0]
            for local_name in local_names:
                aliases[local_name] = replacement

    shifted_aliases = _collect_shifted_anonymous_symbol_aliases(
        anonymous_records,
        global_records,
    )
    for local_name, replacement in shifted_aliases.items():
        aliases.setdefault(local_name, replacement)
    return aliases


def _collect_shifted_anonymous_symbol_aliases(
    anonymous_records: list[dict[str, object]],
    global_records: list[dict[str, object]],
) -> dict[str, str]:
    """Map local ``@N`` symbols to peer globals after a section-offset shift."""
    globals_by_section_size: dict[tuple[str, int], list[dict[str, object]]] = {}
    globals_by_section_value_size: dict[
        tuple[str, int, int], list[str]
    ] = {}
    for sym in global_records:
        section = sym["section"]
        if not isinstance(section, str):
            continue
        value = int(sym["value"])
        size = int(sym["size"])
        globals_by_section_size.setdefault((section, size), []).append(sym)
        globals_by_section_value_size.setdefault(
            (section, value, size),
            [],
        ).append(str(sym["name"]))

    deltas_by_section: dict[str, dict[int, int]] = {}
    for sym in anonymous_records:
        section = sym["section"]
        if not isinstance(section, str):
            continue
        value = int(sym["value"])
        size = int(sym["size"])
        for global_sym in globals_by_section_size.get((section, size), []):
            delta = int(global_sym["value"]) - value
            deltas_by_section.setdefault(section, {})
            deltas_by_section[section][delta] = (
                deltas_by_section[section].get(delta, 0) + 1
            )

    best_delta_by_section: dict[str, int] = {}
    for section, counts in deltas_by_section.items():
        if not counts:
            continue
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        delta, count = ranked[0]
        next_count = ranked[1][1] if len(ranked) > 1 else 0
        min_count = 1 if section == ".sdata" else 2
        if count >= min_count and count > next_count:
            best_delta_by_section[section] = delta

    aliases: dict[str, str] = {}
    for sym in anonymous_records:
        name = str(sym["name"])
        section = sym["section"]
        if not isinstance(section, str) or section not in best_delta_by_section:
            continue
        value = int(sym["value"]) + best_delta_by_section[section]
        size = int(sym["size"])
        candidates = globals_by_section_value_size.get((section, value, size), [])
        if len(candidates) == 1:
            aliases[name] = candidates[0]
    return aliases


def _read_object_symbol_records(obj_path: Path) -> list[dict[str, object]]:
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return []

    try:
        with obj_path.open("rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return []

            symbols: list[dict[str, object]] = []
            for sym in symtab.iter_symbols():
                name = sym.name
                shndx = sym["st_shndx"]
                if not name or not isinstance(shndx, int):
                    continue
                info = sym["st_info"]
                section = elf.get_section(shndx)
                symbols.append({
                    "name": name,
                    "section": section.name if section is not None else None,
                    "shndx": shndx,
                    "value": int(sym["st_value"]),
                    "size": int(sym["st_size"]),
                    "bind": info["bind"],
                    "type": info["type"],
                })
            return symbols
    except (OSError, KeyError, TypeError, ValueError, ELFError):
        return []


def collect_section_anchor_aliases(
    obj_path: Path,
    peer_obj_path: Path | None = None,
) -> dict[str, str]:
    """Map local section aliases to co-located global objects.

    MWCC/dtk can emit a local symbol such as ``...data.0`` at the same
    ``.data`` offset as a real global object, then show ADDR16_HA/LO relocs
    against that local anchor. The linker resolves both to the same address,
    so checkdiff should canonicalize the anchor to the named global before
    comparing disassembly.
    """
    symbols = _read_object_symbol_records(obj_path)
    peer_symbols = (
        _read_object_symbol_records(peer_obj_path)
        if peer_obj_path is not None
        else None
    )
    return _collect_symbol_aliases_by_location(
        symbols,
        peer_symbols=peer_symbols,
    )


def _read_sdata2_8byte_symbol_values(obj_path: Path) -> dict[str, int]:
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return {}

    try:
        with obj_path.open("rb") as f:
            elf = ELFFile(f)
            sdata2 = elf.get_section_by_name(".sdata2")
            symtab = elf.get_section_by_name(".symtab")
            if sdata2 is None or symtab is None:
                return {}
            sdata2_idx = elf.get_section_index(".sdata2")
            data = sdata2.data()
            values: dict[str, int] = {}
            for sym in symtab.iter_symbols():
                if sym["st_shndx"] != sdata2_idx:
                    continue
                name = sym.name
                if not name or name.startswith("."):
                    continue
                if sym["st_size"] != 8:
                    continue
                offset = int(sym["st_value"])
                if offset + 8 > len(data):
                    continue
                values[name] = struct.unpack(">Q", data[offset:offset + 8])[0]
            return values
    except (OSError, KeyError, TypeError, ValueError, ELFError):
        return {}


def collect_sdata2_value_relocation_aliases(
    *obj_paths: Path,
) -> dict[str, str]:
    """Map duplicate-valued 8-byte .sdata2 symbols to value tokens.

    Some TUs contain multiple named labels for the same int-to-float magic
    constant. A freshly built object can only rename an anonymous literal to
    one of those labels, while a specific reference function may relocate
    against another. When both labels point at identical backing bytes, the
    relocation target name is not useful evidence for a code mismatch.
    """
    names_by_value: dict[int, set[str]] = {}
    for obj_path in obj_paths:
        for name, value in _read_sdata2_8byte_symbol_values(obj_path).items():
            names_by_value.setdefault(value, set()).add(name)

    aliases: dict[str, str] = {}
    for value, names in names_by_value.items():
        if len(names) < 2:
            continue
        token = f"__sdata2_value_{value:016x}"
        for name in names:
            aliases[name] = token
    return aliases


def normalize_section_anchor_references(
    lines: list[str],
    aliases: dict[str, str],
) -> list[str]:
    """Replace section-anchor symbol references with equivalent globals."""
    if not aliases:
        return lines
    alternatives = "|".join(
        re.escape(anchor)
        for anchor in sorted(aliases, key=len, reverse=True)
    )
    pattern = re.compile(
        rf"(?<![{_SECTION_ANCHOR_TOKEN_CHARS}])"
        rf"({alternatives})"
        rf"(?![{_SECTION_ANCHOR_TOKEN_CHARS}])"
    )
    return [
        pattern.sub(lambda match: aliases[match.group(1)], line)
        for line in lines
    ]


_RELOC_TARGET_NAME_RE = re.compile(
    r"(?P<name>@\d+|[A-Za-z_.$][A-Za-z0-9_.$]*)"
    r"(?P<suffix>(?:[+-]0x[0-9A-Fa-f]+)?)$"
)


def normalize_sdata2_value_relocation_aliases(
    lines: list[str],
    aliases: dict[str, str],
) -> list[str]:
    """Canonicalize relocation targets for equal-valued .sdata2 aliases."""
    if not aliases:
        return lines

    out: list[str] = []
    for line in lines:
        if not _is_relocation_line(line):
            out.append(line)
            continue
        match = _RELOC_TARGET_NAME_RE.search(line)
        if match is None:
            out.append(line)
            continue
        replacement = aliases.get(match.group("name"))
        if replacement is None:
            out.append(line)
            continue
        out.append(
            f"{line[:match.start('name')]}{replacement}"
            f"{line[match.end('name'):]}"
        )
    return out


def normalize_reloc_line_offsets(lines: list[str]) -> list[str]:
    """Round reloc-line offsets down to the containing 4-byte instruction.

    PowerPC SDA21 relocations target the 16-bit immediate field of an
    instruction. Depending on which tool emitted the asm, the reloc may be
    reported at the instruction's byte offset (e.g. ``+0xc0``) or at the
    immediate-field's offset (+2 from instruction start, e.g. ``+0xc2``).
    objdiff/objdump can disagree between the expected and current .o files,
    which makes opcode-identical functions look mismatched purely on the
    reloc-line offsets.

    PPC instructions are 4-byte aligned, so any reloc emitted on an offset
    that isn't a multiple of 4 must be inside the containing instruction.
    Rounding the reloc-line offset down to the 4-byte boundary makes the
    comparison invariant to this +2 quirk while preserving the relocation's
    semantic meaning (which instruction it applies to).

    Only reloc lines are rewritten; instruction lines are left untouched.
    Lines whose offset prefix can't be parsed are passed through unchanged.
    """
    out: list[str] = []
    for line in lines:
        if not _is_relocation_line(line):
            out.append(line)
            continue
        m = _NORMALIZED_OFFSET_RE.match(line)
        if not m:
            out.append(line)
            continue
        raw_offset = int(m.group(1), 16)
        aligned = raw_offset & ~0x3
        if aligned == raw_offset:
            out.append(line)
            continue
        # Preserve the original hex width so existing alignment in the
        # side-by-side view stays stable.
        width = len(m.group(1))
        sep = m.group(2)
        rest = line[m.end():]
        out.append(f"+{aligned:0{width}x}:{sep}{rest}")
    return out


def _mnemonics(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if line.startswith("<") or _is_relocation_line(line):
            continue
        body = _asm_body(line)
        if not body:
            continue
        result.append(body.split(None, 1)[0])
    return result


def _call_targets(lines: list[str]) -> list[str]:
    targets = []
    for line in lines:
        if _is_relocation_line(line):
            continue
        body = _asm_body(line)
        parts = body.split(None, 1)
        if not parts or parts[0] not in {"bl", "bctrl"}:
            continue
        targets.append(parts[1].strip() if len(parts) > 1 else parts[0])
    return targets


_PHYSICAL_REG_TOKEN_RE = re.compile(r"\b([rf])(?:[0-9]|[12][0-9]|3[01])\b")
_SELF_RELATIVE_CALL_RE = re.compile(
    r"^(?P<base>[A-Za-z_.$][A-Za-z0-9_.$]*)(?P<delta>[+-]0x[0-9A-Fa-f]+)?$"
)
_OFFSET_GPR_OPERAND_RE = re.compile(
    r"^(?P<offset>-?(?:0x[0-9A-Fa-f]+|\d+))\s*"
    r"\(\s*(?P<base>r(?:[0-9]|[12][0-9]|3[01]))\s*\)$"
)


def _normalize_physical_register_tokens(body: str) -> str:
    return _PHYSICAL_REG_TOKEN_RE.sub(r"\1N", body)


def _line_diffs_are_register_token_only(
    ref_lines: list[str],
    our_lines: list[str],
) -> bool:
    if len(ref_lines) != len(our_lines):
        return False
    saw_diff = False
    for ref_line, our_line in zip(ref_lines, our_lines):
        if ref_line == our_line:
            continue
        ref_body = _asm_body(ref_line)
        our_body = _asm_body(our_line)
        if not ref_body or ref_body.startswith("<"):
            continue
        saw_diff = True
        if (
            _normalize_physical_register_tokens(ref_body)
            != _normalize_physical_register_tokens(our_body)
        ):
            return False
    return saw_diff


def _self_relative_call_base(target: str) -> str | None:
    match = _SELF_RELATIVE_CALL_RE.match(target.strip())
    if match is None or match.group("delta") is None:
        return None
    return match.group("base")


def _call_delta_is_self_relative_offset_only(
    ref_calls: list[str],
    our_calls: list[str],
) -> bool:
    if not ref_calls and not our_calls:
        return True
    if len(ref_calls) != len(our_calls):
        return False
    saw_offset_delta = False
    for ref_call, our_call in zip(ref_calls, our_calls):
        if ref_call == our_call:
            continue
        ref_base = _self_relative_call_base(ref_call)
        our_base = _self_relative_call_base(our_call)
        if ref_base is None or our_base is None or ref_base != our_base:
            return False
        saw_offset_delta = True
    return saw_offset_delta


def _single_coalescible_mnemonic_delta(
    ref_mnemonics: list[str],
    our_mnemonics: list[str],
) -> str | None:
    if abs(len(ref_mnemonics) - len(our_mnemonics)) != 1:
        return None
    longer = ref_mnemonics if len(ref_mnemonics) > len(our_mnemonics) else our_mnemonics
    shorter = our_mnemonics if longer is ref_mnemonics else ref_mnemonics
    for idx, mnemonic in enumerate(longer):
        candidate = longer[:idx] + longer[idx + 1:]
        if candidate == shorter and mnemonic in {"mr", "addi"}:
            return mnemonic
    return None


def _parse_int_token(value: str) -> int | None:
    try:
        return int(value, 0)
    except ValueError:
        return None


def _parse_instruction(line: str) -> tuple[str, list[str]] | None:
    body = _asm_body(line)
    parts = body.split(None, 1)
    if len(parts) != 2:
        return None
    return parts[0], _split_operands(parts[1])


def _parse_add_regs(line: str) -> tuple[str, str, str] | None:
    parsed = _parse_instruction(line)
    if parsed is None:
        return None
    opcode, operands = parsed
    if opcode != "add" or len(operands) != 3:
        return None
    if not all(_is_gpr(operand) for operand in operands):
        return None
    return operands[0], operands[1], operands[2]


def _parse_addi_regs(line: str) -> tuple[str, str, int] | None:
    parsed = _parse_instruction(line)
    if parsed is None:
        return None
    opcode, operands = parsed
    if opcode != "addi" or len(operands) != 3:
        return None
    if not _is_gpr(operands[0]) or not _is_gpr(operands[1]):
        return None
    imm = _parse_int_token(operands[2])
    if imm is None:
        return None
    return operands[0], operands[1], imm


def _parse_stw_disp(line: str) -> tuple[str, int, str] | None:
    parsed = _parse_instruction(line)
    if parsed is None:
        return None
    opcode, operands = parsed
    if opcode != "stw" or len(operands) != 2 or not _is_gpr(operands[0]):
        return None
    match = _OFFSET_GPR_OPERAND_RE.match(operands[1])
    if match is None:
        return None
    offset = _parse_int_token(match.group("offset"))
    if offset is None:
        return None
    return operands[0], offset, match.group("base")


def _parse_stwx(line: str) -> tuple[str, str, str] | None:
    parsed = _parse_instruction(line)
    if parsed is None:
        return None
    opcode, operands = parsed
    if opcode != "stwx" or len(operands) != 3:
        return None
    if not all(_is_gpr(operand) for operand in operands):
        return None
    return operands[0], operands[1], operands[2]


def _add_base_index_matches(
    left: str,
    right: str,
    *,
    base: str,
    index: str,
) -> bool:
    return (left == base and right == index) or (left == index and right == base)


def _detect_array_store_addressing_mode_ceiling(
    ref_lines: list[str],
    our_lines: list[str],
) -> dict | None:
    for line_index, (ref_line, our_line) in enumerate(zip(ref_lines, our_lines)):
        ref_add = _parse_add_regs(ref_line)
        our_addi = _parse_addi_regs(our_line)
        if ref_add is None or our_addi is None:
            continue
        ref_ptr, ref_left, ref_right = ref_add
        our_index, our_index_source, our_disp = our_addi
        for store_index in range(
            line_index + 1,
            min(len(ref_lines), len(our_lines), line_index + 5),
        ):
            ref_store = _parse_stw_disp(ref_lines[store_index])
            our_store = _parse_stwx(our_lines[store_index])
            if ref_store is None or our_store is None:
                continue
            ref_value, ref_disp, ref_store_base = ref_store
            our_value, our_base, our_store_index = our_store
            if ref_value != our_value:
                continue
            if ref_store_base != ref_ptr or ref_disp != our_disp:
                continue
            if our_store_index != our_index:
                continue
            if not _add_base_index_matches(
                ref_left,
                ref_right,
                base=our_base,
                index=our_index_source,
            ):
                continue
            return {
                "subclass": "array-element-store-addressing-mode",
                "confidence": "medium",
                "reason": (
                    "array-element store addressing-mode instruction selection: "
                    "target forms an element pointer with add and stores via "
                    "displacement stw, while current folds the displacement into "
                    "the index and emits stwx; this is not register coloring"
                ),
            }
    return None


def detect_backend_ceiling(
    ref_lines: list[str],
    our_lines: list[str],
    ref_mnemonics: list[str],
    our_mnemonics: list[str],
    ref_calls: list[str],
    our_calls: list[str],
) -> dict | None:
    """Return cheap upfront backend-ceiling classification evidence."""
    addressing_mode = _detect_array_store_addressing_mode_ceiling(
        ref_lines,
        our_lines,
    )
    if addressing_mode:
        return addressing_mode

    if ref_mnemonics == our_mnemonics and _line_diffs_are_register_token_only(
        ref_lines,
        our_lines,
    ):
        return {
            "subclass": "coloring-rotation",
            "confidence": "high",
            "reason": (
                "opcode sequence is identical and all paired differences are "
                "register-token-only swaps"
            ),
        }

    coalescible = _single_coalescible_mnemonic_delta(ref_mnemonics, our_mnemonics)
    if coalescible and _call_delta_is_self_relative_offset_only(ref_calls, our_calls):
        return {
            "subclass": "coalesce",
            "confidence": "medium",
            "reason": (
                f"single coalescible {coalescible} instruction count delta; "
                "call-shape delta is only self-relative bl offset churn"
            ),
        }

    return None


def _has_source_actionable_register_guidance(guidance: dict | None) -> bool:
    if not guidance:
        return False
    return bool(
        guidance.get("volatile_target_registers")
        or guidance.get("volatile_current_registers")
        or guidance.get("callee_swap_pairs")
        or guidance.get("suggestions")
    )


def _branch_shape(lines: list[str]) -> list[str]:
    shape = []
    for mnemonic in _mnemonics(lines):
        if mnemonic in {"bl", "bctrl", "blr"}:
            continue
        if mnemonic.startswith("b"):
            shape.append(mnemonic)
    return shape


def _detect_inline_boundary_artifact(
    ref_lines: list[str],
    our_lines: list[str],
    ref_calls: list[str],
    our_calls: list[str],
) -> Optional[dict]:
    missing_ref_calls = [call for call in ref_calls if call not in our_calls]
    if not missing_ref_calls or len(our_lines) <= len(ref_lines):
        return None

    expected_frame = _stack_frame_size(ref_lines)
    current_frame = _stack_frame_size(our_lines)
    frame_growth = None
    if expected_frame is not None and current_frame is not None:
        frame_growth = current_frame - expected_frame

    our_mnemonics = _mnemonics(our_lines)
    inline_like_ops = {
        "fabs",
        "fadds",
        "fdivs",
        "fmadds",
        "fmr",
        "fmuls",
        "fneg",
        "frsqrte",
        "fsubs",
        "psq_l",
        "psq_st",
    }
    has_inline_body_shape = (
        len(our_lines) - len(ref_lines) >= 3
        or any(op in inline_like_ops for op in our_mnemonics)
        or (frame_growth is not None and frame_growth > 0)
    )
    if not has_inline_body_shape:
        return None
    return {
        "missing_ref_calls": missing_ref_calls,
        "line_growth": len(our_lines) - len(ref_lines),
        "size_verdict": "current-larger",
        "expected_frame_size": expected_frame,
        "current_frame_size": current_frame,
        "frame_growth": frame_growth,
    }


_REG_RE = re.compile(r"^r(?:[0-9]|[12][0-9]|3[01])$")
_STRUCT_INDEXED_OPS = {
    "lbzx",
    "lhzx",
    "lhax",
    "lwzx",
    "lfsx",
    "lfdx",
    "stbx",
    "sthx",
    "stwx",
    "stfsx",
    "stfdx",
}
_STRUCT_OFFSET_OPS = {
    "lbz",
    "lha",
    "lhz",
    "lwz",
    "lfs",
    "lfd",
    "stb",
    "sth",
    "stw",
    "stfs",
    "stfd",
}
_REG_OFFSET_OPERAND_RE = re.compile(
    r"^(?:-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*(r(?:[0-9]|[12][0-9]|3[01]))\s*\)$"
)


def _split_operands(operands: str) -> list[str]:
    return [operand.strip() for operand in operands.split(",") if operand.strip()]


def _is_gpr(token: str) -> bool:
    return _REG_RE.match(token) is not None


def detect_indexed_struct_pointer_materialization(
    ref_lines: list[str],
    our_lines: list[str],
) -> Optional[dict]:
    expected_indexed_ops: list[dict] = []
    for line_index, line in enumerate(ref_lines):
        body = _asm_body(line)
        parts = body.split(None, 1)
        if len(parts) != 2 or parts[0] not in _STRUCT_INDEXED_OPS:
            continue
        operands = _split_operands(parts[1])
        if len(operands) >= 3 and _is_gpr(operands[-2]) and _is_gpr(operands[-1]):
            expected_indexed_ops.append({
                "line_index": line_index,
                "opcode": parts[0],
                "body": body,
            })

    current_materialized: list[dict] = []
    for line_index, line in enumerate(our_lines):
        body = _asm_body(line)
        parts = body.split(None, 1)
        if len(parts) != 2 or parts[0] != "add":
            continue
        operands = _split_operands(parts[1])
        if len(operands) != 3 or not all(_is_gpr(operand) for operand in operands):
            continue
        pointer_reg = operands[0]
        field_accesses: list[dict] = []
        for nearby_index in range(line_index + 1, min(len(our_lines), line_index + 5)):
            nearby_body = _asm_body(our_lines[nearby_index])
            nearby_parts = nearby_body.split(None, 1)
            if len(nearby_parts) != 2 or nearby_parts[0] not in _STRUCT_OFFSET_OPS:
                continue
            nearby_operands = _split_operands(nearby_parts[1])
            if not nearby_operands:
                continue
            if any(
                (match := _REG_OFFSET_OPERAND_RE.match(operand))
                and match.group(1) == pointer_reg
                for operand in nearby_operands
            ):
                field_accesses.append({
                    "line_index": nearby_index,
                    "body": nearby_body,
                })
        if field_accesses:
            current_materialized.append({
                "line_index": line_index,
                "add": body,
                "pointer_register": pointer_reg,
                "field_accesses": field_accesses,
            })

    if not expected_indexed_ops or not current_materialized:
        return None
    return {
        "expected_indexed_ops": expected_indexed_ops,
        "current_materialized_pointers": current_materialized,
    }


def format_indexed_struct_pointer_materialization_diagnostic(diag: dict) -> str:
    expected_count = len(diag.get("expected_indexed_ops") or [])
    current_count = len(diag.get("current_materialized_pointers") or [])
    return (
        "indexed struct array pointer-shape hint: expected keeps the array base "
        f"plus byte/index offset for {expected_count} indexed "
        f"{_plural(expected_count, 'load/store')}, while current materializes an "
        "element pointer shape "
        f"{current_count} element {_plural(current_count, 'pointer')} with add "
        "and then accesses fields through that pointer. For MWCC, split "
        "the first field into a scalar local and keep later dyn_desc/"
        "field accesses as direct array.base+offset expressions; avoid a live "
        "per-element pointer across calls or loops."
    )


_STACK_FRAME_ALLOC_RE = re.compile(
    r"\bstwu\s+r1\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)"
)
_STACK_SLOT_RE = re.compile(r"(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\(\s*r1\s*\)")
_PAD_STACK_RE = re.compile(r"\bPAD_STACK\s*\(\s*(\d+)\s*\)")
_MANUAL_STACK_PADDING_RE = re.compile(
    r"\bUNUSED\s+"
    r"(?:(?:volatile|const)\s+)*"
    r"(?:(?:unsigned\s+)?char|u8|s8)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\[\s*(?P<size>0x[0-9A-Fa-f]+|\d+)\s*\]\s*;"
)


def _stack_frame_size(lines: list[str]) -> Optional[int]:
    for line in lines:
        match = _STACK_FRAME_ALLOC_RE.search(_asm_body(line))
        if match:
            return abs(int(match.group(1), 0))
    return None


def _struct_key(body: str) -> str:
    """Mask displacement + branch targets so equal-shape instructions align."""
    k = re.sub(r"-?(?:0x[0-9a-fA-F]+|\d+)\((r\d+)\)", r"DISP(\1)", body)
    k = re.sub(r"<[^>]*>", "TGT", k)
    return re.sub(r"\s+", " ", k).strip()


_MEMOP_RE = re.compile(r"^([a-z][a-z0-9.]*)\s+.*?(-?(?:0x[0-9a-fA-F]+|\d+))\((r\d+)\)")


def _paired_struct_offset_delta(ref_body: str, our_body: str):
    """Return a struct-offset discrepancy dict, or None.

    Same mnemonic + non-stack/SDA bases + differing displacement.
    """
    rm = _MEMOP_RE.match(ref_body.strip())
    cm = _MEMOP_RE.match(our_body.strip())
    if not rm or not cm:
        return None
    if rm.group(1) != cm.group(1):         # mnemonic must match
        return None
    ref_base = rm.group(3)
    cur_base = cm.group(3)
    if ref_base in ("r1", "r2", "r13") or cur_base in ("r1", "r2", "r13"):
        return None

    def _d(s: str) -> int:
        s = s.strip()
        if s.lower().startswith(("0x", "-0x")):
            return int(s, 16)
        return int(s)

    rd, cd = _d(rm.group(2)), _d(cm.group(2))
    if rd == cd:
        return None
    return {
        "base_reg": cur_base,
        "ref_base_reg": ref_base,
        "cur_base_reg": cur_base,
        "mnemonic": rm.group(1),
        "ref_disp": rd,
        "cur_disp": cd,
    }


def _offset_discrepancy_bodies(lines: list[str]) -> list[str]:
    """Return instruction bodies used for struct offset pairing.

    Normalized disassembly includes a function header line. Offset indices must
    refer to instruction rows so downstream access-index traces line up.
    """
    bodies: list[str] = []
    for line in lines:
        if _is_relocation_line(line):
            continue
        body = _asm_body(line)
        if not body or body.startswith("<"):
            continue
        bodies.append(body)
    return bodies


def _paired_stack_delta(ref_body: str, our_body: str) -> Optional[int]:
    ref_frame = _STACK_FRAME_ALLOC_RE.search(ref_body)
    our_frame = _STACK_FRAME_ALLOC_RE.search(our_body)
    if ref_frame and our_frame:
        return abs(int(ref_frame.group(1), 0)) - abs(int(our_frame.group(1), 0))

    ref_slots = _STACK_SLOT_RE.findall(ref_body)
    our_slots = _STACK_SLOT_RE.findall(our_body)
    if len(ref_slots) != 1 or len(our_slots) != 1:
        return None
    ref_offset = int(ref_slots[0], 0)
    our_offset = int(our_slots[0], 0)
    if ref_offset < 0 or our_offset < 0:
        return None
    return ref_offset - our_offset


def detect_stack_slot_localizer(ref_lines: list[str], our_lines: list[str]) -> Optional[dict]:
    expected_frame = _stack_frame_size(ref_lines)
    current_frame = _stack_frame_size(our_lines)
    if (
        expected_frame is not None
        and current_frame is not None
        and expected_frame != current_frame
    ):
        return None

    mismatches: list[dict] = []
    for line_index, (ref_line, our_line) in enumerate(zip(ref_lines, our_lines)):
        if ref_line == our_line:
            continue
        ref_body = _asm_body(ref_line)
        our_body = _asm_body(our_line)
        ref_slots = _STACK_SLOT_RE.findall(ref_body)
        our_slots = _STACK_SLOT_RE.findall(our_body)
        if len(ref_slots) != 1 or len(our_slots) != 1:
            continue
        ref_offset = int(ref_slots[0], 0)
        our_offset = int(our_slots[0], 0)
        if ref_offset < 0 or our_offset < 0 or ref_offset == our_offset:
            continue
        ref_opcode = ref_body.split(None, 1)[0] if ref_body.split() else ""
        our_opcode = our_body.split(None, 1)[0] if our_body.split() else ""
        if ref_opcode != our_opcode:
            continue
        mismatches.append({
            "line_index": line_index,
            "expected_offset": ref_offset,
            "current_offset": our_offset,
            "delta": ref_offset - our_offset,
            "opcode": ref_opcode,
            "expected": ref_body,
            "current": our_body,
        })

    if not mismatches:
        return None
    return {
        "frame_size": expected_frame if expected_frame == current_frame else None,
        "mismatch_count": len(mismatches),
        "deltas": sorted({item["delta"] for item in mismatches}),
        "mismatches": mismatches,
    }


def detect_stack_frame_delta(ref_lines: list[str], our_lines: list[str]) -> Optional[dict]:
    expected_frame = _stack_frame_size(ref_lines)
    current_frame = _stack_frame_size(our_lines)
    if expected_frame is None or current_frame is None:
        return None
    missing_stack = expected_frame - current_frame
    if missing_stack == 0:
        return None

    paired_deltas: list[int] = []
    for ref_line, our_line in zip(ref_lines, our_lines):
        if ref_line == our_line:
            continue
        delta = _paired_stack_delta(_asm_body(ref_line), _asm_body(our_line))
        if delta is not None:
            paired_deltas.append(delta)

    consistent_delta: Optional[int] = None
    if paired_deltas and all(delta == paired_deltas[0] for delta in paired_deltas):
        consistent_delta = paired_deltas[0]

    return {
        "expected_frame_size": expected_frame,
        "current_frame_size": current_frame,
        "missing_stack_bytes": missing_stack,
        "consistent_stack_slot_delta": consistent_delta,
        "stack_slot_delta_count": len(paired_deltas),
    }


def detect_diagnostic_pad_stack(function_body: Optional[str]) -> Optional[dict]:
    if not function_body:
        return None
    pad_stack_bytes = [
        int(match.group(1), 10)
        for match in _PAD_STACK_RE.finditer(function_body)
    ]
    manual_padding = [
        {
            "name": match.group("name"),
            "bytes": int(match.group("size"), 0),
        }
        for match in _MANUAL_STACK_PADDING_RE.finditer(function_body)
    ]
    if not pad_stack_bytes and not manual_padding:
        return None
    result = {
        "pad_stack_bytes": pad_stack_bytes,
        "total_pad_stack_bytes": (
            sum(pad_stack_bytes)
            + sum(item["bytes"] for item in manual_padding)
        ),
    }
    if manual_padding:
        result["manual_padding"] = manual_padding
    return result


def detect_diagnostic_pad_stack_in_source(
    source_path: Path,
    func_name: str,
) -> Optional[dict]:
    if extract_function_body is None:
        return None
    body = extract_function_body(source_path, func_name)
    return detect_diagnostic_pad_stack(body)


def _pad_stack_expr(pad_stack_bytes: list[int]) -> str:
    if not pad_stack_bytes:
        return "0"
    if len(pad_stack_bytes) == 1:
        return str(pad_stack_bytes[0])
    return "+".join(str(n) for n in pad_stack_bytes) + f"={sum(pad_stack_bytes)}"


def _manual_padding_expr(items: list[dict]) -> str:
    if not items:
        return ""
    return ", ".join(f"{item['name']}[{item['bytes']}]" for item in items)


def _source_reservation_guidance(
    reservation_bytes: int,
    *,
    consistent_stack_slot_delta: Optional[int] = None,
    stack_slot_delta_count: int = 0,
    pad_label: Optional[str] = None,
) -> list[str]:
    size = abs(reservation_bytes)
    if reservation_bytes > 0:
        if pad_label:
            lead = (
                f"do not commit {pad_label}; replace it with natural C that "
                f"reserves {size} bytes"
            )
        else:
            lead = (
                f"do not commit PAD_STACK({size}); use it only to prove a "
                f"{size}-byte frame-reservation gap"
            )
    else:
        lead = (
            f"current source reserves {size} extra bytes; remove diagnostic "
            "padding or shorten the natural local lifetime"
        )
    guidance = [
        lead,
        "try a real local array/struct, address-taken local, or volatile temp "
        "when the original likely needed a stack slot",
        "try call-argument temporary locals around the calls or inlined "
        "helpers closest to the shifted stack references",
        "adjust local lifetimes by declaring/initializing a temp earlier or "
        "keeping it live across the call that needs the slot",
    ]
    if consistent_stack_slot_delta is not None and stack_slot_delta_count:
        guidance.append(
            f"{stack_slot_delta_count} paired r1 stack references shift by "
            f"{consistent_stack_slot_delta} bytes; use those shifted offsets "
            "as the stack-slot map for the local/temp to materialize"
        )
    return guidance


def _format_source_reservation_guidance(guidance: list[str]) -> str:
    return "; ".join(guidance)


def format_stack_frame_diagnostic(classification: dict) -> Optional[str]:
    diag = classification.get("stack_frame_delta")
    if not diag:
        return None
    expected = diag["expected_frame_size"]
    current = diag["current_frame_size"]
    missing = diag["missing_stack_bytes"]
    if missing > 0:
        action = (
            f"current frame is {missing} bytes smaller than expected; "
            f"a non-shipping PAD_STACK({missing}) probe should test whether "
            "the remaining mismatch is only frame reservation"
        )
    else:
        action = (
            f"current frame is {-missing} bytes larger than expected; remove "
            "diagnostic padding or look for a natural source shape with a "
            "smaller stack reservation"
        )
    source_guidance = _format_source_reservation_guidance(
        _source_reservation_guidance(
            missing,
            consistent_stack_slot_delta=diag.get("consistent_stack_slot_delta"),
            stack_slot_delta_count=diag.get("stack_slot_delta_count", 0),
        )
    )
    return (
        "diagnostic stack-frame probe: "
        f"expected frame={expected} bytes, current frame={current} bytes; "
        f"{action}. If this checkdiff run is paired with forced scheduler "
        "swaps, a clean probe result means diagnostic match: "
        "frame-reservation + schedule. source-level next steps: "
        f"{source_guidance}."
    )


def format_stack_slot_localizer_diagnostic(classification: dict) -> Optional[str]:
    diag = classification.get("stack_slot_localizer")
    if not diag:
        return None
    count = diag.get("mismatch_count", 0)
    mismatches = diag.get("mismatches") or []
    examples = []
    for item in mismatches[:3]:
        examples.append(
            f"{item.get('opcode')} expected 0x{item.get('expected_offset'):x}(r1) "
            f"but current uses 0x{item.get('current_offset'):x}(r1)"
        )
    frame = diag.get("frame_size")
    frame_text = (
        f"frame size already matches at {frame} bytes"
        if frame is not None
        else "frame size is unchanged/unknown"
    )
    bridge_text = None
    if render_stack_slot_bridge_summary is not None:
        bridge = diag.get("pcdump_bridge")
        if isinstance(bridge, dict):
            bridge_text = render_stack_slot_bridge_summary(bridge)
    return (
        "compiler-temp spill slot localizer: "
        f"{frame_text}, but {count} paired r1 stack "
        f"{_plural(count, 'reference')} use different offsets"
        + (f" ({'; '.join(examples)})" if examples else "")
        + ". This is a stack-slot placement mismatch, not a frame "
        "reservation problem. Target the unnamed compiler temp/spill slot "
        "independently of named locals: try retiming a sqrt/call-result temp, "
        "a narrow address-taken or volatile temp around the producer/consumer, "
        "or source-shape probes that preserve already-correct named-local offsets."
        + (f" {bridge_text}." if bridge_text else "")
    )


def _detect_reserved_low_spill_region_candidate(
    classification: dict,
    probe: dict,
) -> Optional[dict]:
    localizer = classification.get("stack_slot_localizer")
    if not isinstance(localizer, dict):
        return None
    if not probe.get("total_pad_stack_bytes"):
        return None
    if localizer.get("frame_size") is None:
        return None
    deltas = localizer.get("deltas")
    if not isinstance(deltas, list) or not deltas:
        return None
    if not all(isinstance(delta, int) and delta > 0 for delta in deltas):
        return None

    return {
        "status": "heuristic",
        "kind": "reserved-unused-low-spill-region",
        "confidence": "medium",
        "deltas": list(deltas),
        "diagnostic_pad_stack_bytes": probe.get("total_pad_stack_bytes"),
        "closability_tier": "ceiling",
        "source_transform_closability": "no-known-c-source-lever",
        "reason": (
            "diagnostic stack padding is present and the frame size already "
            "matches, but the current stack object remains below the expected "
            "offset; likely extra reserved-but-unused compiler spill/local "
            "area below an inlined or address-taken local"
        ),
        "next_command": (
            "melee-agent debug inspect frame-reservations -f <function> "
            "--expected-asm <expected.s> --json"
        ),
    }


def format_reserved_low_spill_region_diagnostic(candidate: dict) -> str:
    deltas = candidate.get("deltas") or []
    delta_text = ",".join(str(delta) for delta in deltas) or "unknown"
    return (
        "reserved-but-unused low spill region candidate: frame size already "
        "matches after diagnostic padding, but expected stack local offsets "
        f"remain higher by {delta_text} byte(s). Treat this as a frame/local-area "
        "ceiling with no known C-source lever; do not keep adding PAD_STACK or "
        "dummy named locals, because those reserve above the affected object. "
        f"next: {candidate.get('next_command')}"
    )


def add_stack_slot_pcdump_bridge(
    classification: dict,
    *,
    function: str,
    pcdump_text: Optional[str] = None,
    pcdump_path: Optional[Path] = None,
    source_text: Optional[str] = None,
    source_file: Optional[str] = None,
) -> None:
    if explain_stack_slot_localizer is None:
        return
    localizer = classification.get("stack_slot_localizer")
    if not isinstance(localizer, dict):
        return
    if pcdump_text is None and pcdump_path is not None:
        try:
            pcdump_text = pcdump_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            localizer["pcdump_bridge_error"] = str(exc)
            return
    if not pcdump_text:
        return
    report = explain_stack_slot_localizer(
        pcdump_text,
        function,
        localizer,
        source_text=source_text,
        source_file=source_file,
    )
    localizer["pcdump_bridge"] = report
    if render_stack_slot_bridge_summary is None:
        return
    summary = render_stack_slot_bridge_summary(report)
    if not summary:
        return
    reasons = classification.setdefault("reasons", [])
    if summary not in reasons:
        reasons.append(summary)


def format_pad_stack_probe_diagnostic(classification: dict) -> Optional[str]:
    probe = classification.get("diagnostic_pad_stack")
    if not probe:
        return None
    pad_stack_bytes = probe.get("pad_stack_bytes") or []
    total = probe.get("total_pad_stack_bytes")
    if not total:
        return None
    manual_padding = probe.get("manual_padding") or []
    if manual_padding and not pad_stack_bytes:
        pad_label = f"manual stack padding {_manual_padding_expr(manual_padding)}"
        diagnostic_label = f"diagnostic {pad_label}"
    elif manual_padding:
        pad_label = (
            f"PAD_STACK probes ({_pad_stack_expr(pad_stack_bytes)}) plus "
            f"manual stack padding {_manual_padding_expr(manual_padding)}"
        )
        diagnostic_label = f"diagnostic {pad_label}"
    elif len(pad_stack_bytes) == 1:
        pad_label = f"PAD_STACK({pad_stack_bytes[0]})"
        diagnostic_label = f"diagnostic {pad_label}"
    else:
        pad_label = f"PAD_STACK probes ({_pad_stack_expr(pad_stack_bytes)})"
        diagnostic_label = f"diagnostic {pad_label}"
    source_guidance = _format_source_reservation_guidance(
        _source_reservation_guidance(
            int(total),
            pad_label=pad_label,
        )
    )
    return (
        "source-level stack reservation guidance: "
        f"{diagnostic_label} is present. If this run matches or is near-match, "
        f"treat it as evidence for a frame-reservation gap of {total} bytes, "
        f"not shippable source. source-level next steps: {source_guidance}."
    )


def add_pad_stack_probe_guidance(
    classification: dict,
    probe: Optional[dict],
) -> None:
    if not probe:
        return
    classification["diagnostic_pad_stack"] = probe
    reserved_low_spill = _detect_reserved_low_spill_region_candidate(
        classification,
        probe,
    )
    if reserved_low_spill:
        localizer = classification.get("stack_slot_localizer")
        if isinstance(localizer, dict):
            localizer["reserved_low_spill_region"] = reserved_low_spill
        classification["stack_slot_layout_cause"] = reserved_low_spill
        message = format_reserved_low_spill_region_diagnostic(
            reserved_low_spill,
        )
        reasons = classification.setdefault("reasons", [])
        if message not in reasons:
            reasons.append(message)
        return
    message = format_pad_stack_probe_diagnostic(classification)
    if not message:
        return
    reasons = classification.setdefault("reasons", [])
    if message not in reasons:
        reasons.append(message)


def _register_tokens(text: str) -> list[str]:
    return [match.group(0) for match in _REGISTER_TOKEN_RE.finditer(text)]


def _is_gpr(reg: str) -> bool:
    return reg.startswith("r")


def _gpr_num(reg: str) -> int:
    return int(reg[1:])


def _is_volatile_gpr(reg: str) -> bool:
    return _is_gpr(reg) and (_gpr_num(reg) == 0 or 3 <= _gpr_num(reg) <= 12)


def _is_callee_gpr(reg: str) -> bool:
    return _is_gpr(reg) and 25 <= _gpr_num(reg) <= 31


def _sorted_regs(regs: set[str]) -> list[str]:
    return sorted(regs, key=lambda reg: (reg[0], int(reg[1:])))


def detect_register_allocation_guidance(
    ref_lines: list[str],
    our_lines: list[str],
) -> Optional[dict]:
    register_only_count = 0
    volatile_targets: set[str] = set()
    volatile_currents: set[str] = set()
    callee_edges: set[tuple[str, str]] = set()

    for ref_line, our_line in zip(ref_lines, our_lines):
        if ref_line == our_line:
            continue
        ref_body = _asm_body(ref_line)
        our_body = _asm_body(our_line)
        if _normalize_register_tokens(ref_body) != _normalize_register_tokens(our_body):
            continue
        register_only_count += 1
        for ref_reg, cur_reg in zip(_register_tokens(ref_body), _register_tokens(our_body)):
            if ref_reg == cur_reg:
                continue
            if _is_volatile_gpr(ref_reg):
                volatile_targets.add(ref_reg)
            if _is_volatile_gpr(cur_reg):
                volatile_currents.add(cur_reg)
            if _is_callee_gpr(ref_reg) and _is_callee_gpr(cur_reg):
                callee_edges.add((ref_reg, cur_reg))

    if register_only_count == 0:
        return None

    callee_swap_pairs: list[list[str]] = []
    seen_swaps: set[frozenset[str]] = set()
    for left, right in sorted(callee_edges):
        if left == right or (right, left) not in callee_edges:
            continue
        key = frozenset((left, right))
        if key in seen_swaps:
            continue
        seen_swaps.add(key)
        callee_swap_pairs.append(_sorted_regs({left, right}))

    guidance: dict = {
        "register_only_count": register_only_count,
        "volatile_target_registers": _sorted_regs(volatile_targets),
        "volatile_current_registers": _sorted_regs(volatile_currents),
        "callee_swap_pairs": callee_swap_pairs,
    }

    suggestions: list[str] = []
    if volatile_targets:
        suggestions.append(
            "inspect volatile targets with `debug target match-iter-first "
            "-f <function> --regs gpr-volatile,r0`; if the target vector "
            "already satisfied all requested registers, pivot to source "
            "lifetime/callee-save shape instead of force-vector probes; for "
            "flag/reload predicate diffs, try u8/bool/int flag type, "
            "pointer-vs-bool predicate, or short liveness nudges"
        )
    if callee_swap_pairs:
        pairs = ", ".join("<->".join(pair) for pair in callee_swap_pairs)
        suggestions.append(
            f"callee-save swap {pairs} suggests branch-local loop-counter reuse, "
            "nested declaration order, or tree-index vs cursor-increment source "
            "perturbations"
        )
    guidance["suggestions"] = suggestions
    return guidance


def format_register_allocation_guidance(guidance: dict) -> str:
    parts = [
        "register-allocation guidance:",
        f"{guidance.get('register_only_count', 0)} opcode-aligned paired "
        "instruction(s) differ only by register",
    ]
    volatile_targets = guidance.get("volatile_target_registers") or []
    if volatile_targets:
        parts.append(
            "volatile target regs "
            f"{','.join(volatile_targets)}; run "
            "`debug target match-iter-first -f <function> --regs "
            "gpr-volatile,r0`; if the target vector already satisfied all "
            "requested registers, pivot to source lifetime/callee-save shape "
            "instead of force-vector probes; otherwise inspect flag/reload "
            "predicate bindings"
        )
    callee_swaps = guidance.get("callee_swap_pairs") or []
    if callee_swaps:
        pairs = ", ".join("<->".join(pair) for pair in callee_swaps)
        parts.append(
            f"callee-save swap {pairs}; try loop-counter reuse, nested "
            "declaration order, tree-index vs cursor-increment, or "
            "discard/self-assignment liveness nudges"
        )
    return "; ".join(parts)


def classify_asm_diff(ref_lines: list[str], our_lines: list[str]) -> dict:
    """Best-effort classification to help agents avoid chasing false leads."""
    if ref_lines == our_lines:
        return {
            "primary": "instruction-identical",
            "reasons": ["normalized disassembly is identical"],
        }

    bss_anchor_relocations = detect_bss_anchor_relocations(ref_lines, our_lines)

    if _strip_relocation_lines(ref_lines) == _strip_relocation_lines(our_lines):
        if bss_anchor_relocations:
            return {
                "primary": "bss-anchor-ceiling",
                "reasons": [
                    _format_bss_anchor_relocation_diagnostic(
                        bss_anchor_relocations
                    )
                ],
                "bss_anchor_relocations": bss_anchor_relocations,
            }
        return {
            "primary": "relocation-label-only",
            "reasons": ["only relocation annotation lines differ"],
        }

    reasons = []
    ref_mnemonics = _mnemonics(ref_lines)
    our_mnemonics = _mnemonics(our_lines)
    ref_calls = _call_targets(ref_lines)
    our_calls = _call_targets(our_lines)
    ref_branch_shape = _branch_shape(ref_lines)
    our_branch_shape = _branch_shape(our_lines)
    branch_shape_differs = ref_branch_shape != our_branch_shape
    inline_boundary_artifact = _detect_inline_boundary_artifact(
        ref_lines,
        our_lines,
        ref_calls,
        our_calls,
    )
    indexed_struct_pointer_materialization = (
        detect_indexed_struct_pointer_materialization(ref_lines, our_lines)
    )
    register_allocation_guidance = detect_register_allocation_guidance(
        ref_lines,
        our_lines,
    )
    backend_ceiling = detect_backend_ceiling(
        ref_lines,
        our_lines,
        ref_mnemonics,
        our_mnemonics,
        ref_calls,
        our_calls,
    )
    value_numbering_ceiling = (
        detect_divide_rematerialization_ceiling(
            function="<checkdiff>",
            expected_asm_text="\n".join(ref_lines),
            current_asm_lines=our_lines,
        )
        if detect_divide_rematerialization_ceiling is not None
        else None
    )
    if value_numbering_ceiling:
        backend_ceiling = {
            "subclass": "cse-vs-rematerialized-divconst",
            "confidence": value_numbering_ceiling.get("confidence", "medium"),
            "reason": (
                "value-numbering ceiling: target rematerializes a signed "
                "magic divide quotient while current CSEs the quotient across "
                "the branch value use"
            ),
        }
    if (
        backend_ceiling
        and backend_ceiling.get("subclass") == "coloring-rotation"
        and _has_source_actionable_register_guidance(register_allocation_guidance)
    ):
        backend_ceiling = None

    if len(ref_lines) != len(our_lines):
        reasons.append(f"line count differs: expected {len(ref_lines)}, current {len(our_lines)}")

    if ref_mnemonics == our_mnemonics:
        reasons.append("opcode sequence matches; differences are operands, registers, labels, or offsets")
        primary = "operand-register-or-offset"
    else:
        primary = "instruction-sequence"

    if backend_ceiling:
        reasons.append(
            "backend ceiling candidate: " + str(backend_ceiling["reason"])
        )
        primary = "backend-ceiling"

    if len(ref_lines) != len(our_lines) and branch_shape_differs:
        if backend_ceiling:
            reasons.append(
                "control-flow/source shape also differs; inspect separately "
                "if the backend ceiling does not explain all hunks"
            )
        else:
            reasons.append(
                "control-flow/source shape differs: branch shape differs before "
                "downstream operand, stack, or relocation noise"
            )
            primary = "control-flow-source-shape"

    stack_frame_delta = (
        detect_stack_frame_delta(ref_lines, our_lines)
        if ref_mnemonics == our_mnemonics else None
    )
    stack_slot_localizer = (
        detect_stack_slot_localizer(ref_lines, our_lines)
        if ref_mnemonics == our_mnemonics else None
    )

    if ref_calls != our_calls:
        if backend_ceiling:
            reasons.append(
                "call shape also differs after alignment; inspect prototypes, "
                "return types, and inline boundaries if the backend ceiling "
                "does not explain all hunks"
            )
        else:
            reasons.append(
                "call shape differs; check prototypes, return types, and "
                "inline boundaries"
            )
            if primary != "control-flow-source-shape":
                primary = "signature-type-mismatch"

    paired = list(zip(ref_lines, our_lines))
    stack_offset_diffs = 0
    data_symbol_diffs = 0
    likely_register_diffs = 0
    for ref_line, our_line in paired:
        if ref_line == our_line:
            continue
        ref_body = _asm_body(ref_line)
        our_body = _asm_body(our_line)
        if "(r1)" in ref_body and "(r1)" in our_body:
            stack_offset_diffs += 1
        if any(token in ref_body or token in our_body for token in ("@sda", ".sdata", ".data", ".bss", "R_PPC_")):
            data_symbol_diffs += 1
        if re.sub(r"\br(?:[0-9]|[12][0-9]|3[01])\b", "rN", ref_body) == re.sub(
            r"\br(?:[0-9]|[12][0-9]|3[01])\b", "rN", our_body
        ):
            likely_register_diffs += 1

    if stack_offset_diffs:
        reasons.append(f"{stack_offset_diffs} differing paired lines reference stack slots")
        if primary == "operand-register-or-offset":
            primary = "stack-layout"
    if stack_frame_delta:
        hint = format_stack_frame_diagnostic({
            "stack_frame_delta": stack_frame_delta,
        })
        if hint:
            reasons.append(hint)
        if primary == "operand-register-or-offset":
            primary = "stack-layout"
    if stack_slot_localizer:
        hint = format_stack_slot_localizer_diagnostic({
            "stack_slot_localizer": stack_slot_localizer,
        })
        if hint:
            reasons.append(hint)
        if primary in {"operand-register-or-offset", "stack-layout"}:
            primary = "stack-slot-layout"
    if data_symbol_diffs:
        reasons.append(f"{data_symbol_diffs} differing paired lines reference data/symbol relocations")
        if primary == "operand-register-or-offset":
            primary = "data-symbol-or-relocation"
    if bss_anchor_relocations:
        reasons.append(
            _format_bss_anchor_relocation_diagnostic(bss_anchor_relocations)
        )
    if likely_register_diffs:
        reasons.append(f"{likely_register_diffs} differing paired lines look register-only after normalization")
        if primary == "operand-register-or-offset":
            primary = "register-allocation"
    if register_allocation_guidance:
        reasons.append(format_register_allocation_guidance(
            register_allocation_guidance
        ))

    if inline_boundary_artifact:
        calls = ", ".join(inline_boundary_artifact["missing_ref_calls"])
        reasons.append(
            f"reference calls {calls} but current omits that call and is larger; "
            "likely wibo/local compiler inlined locally across an inline boundary"
        )
        primary = "inline-boundary-toolchain-artifact"
    if indexed_struct_pointer_materialization:
        reasons.append(format_indexed_struct_pointer_materialization_diagnostic(
            indexed_struct_pointer_materialization
        ))
        if primary == "register-allocation" and register_allocation_guidance:
            reasons.append(
                "indexed pointer-shape hint demoted because opcode-aligned "
                "register-allocation evidence is stronger"
            )
        elif primary in {"instruction-sequence", "operand-register-or-offset"}:
            primary = "indexed-struct-pointer-materialization"

    structural_truth_gate = normalized_structural_diff(ref_lines, our_lines)
    normalized_diff_lines = structural_truth_gate["normalized_diff_lines"]
    stack_layout_evidence = (
        stack_frame_delta is not None
        or stack_slot_localizer is not None
        or primary in {"stack-layout", "stack-slot-layout"}
    )
    if normalized_diff_lines == 0:
        reasons.insert(
            0,
            "normalized structural diff is zero after masking registers, "
            "immediates, labels, and relocation symbols; treat raw banner "
            "differences as coloring/presentation evidence, not source-shape proof",
        )
        if not stack_layout_evidence:
            primary = "normalized-structural-match"
    elif normalized_diff_lines <= 3:
        reasons.insert(
            0,
            f"normalized structural diff is near-zero ({normalized_diff_lines} "
            "line(s)); inspect as a coloring/alignment cascade before changing "
            "source shape",
        )
        if (
            not stack_layout_evidence
            and primary in {
                "instruction-sequence",
                "signature-type-mismatch",
                "data-symbol-or-relocation",
                "inline-boundary-toolchain-artifact",
                "operand-register-or-offset",
                "register-allocation",
            }
        ):
            primary = "normalized-structural-near-match"

    if not reasons:
        reasons.append("differences require direct inspection")

    # Compute offset_discrepancies via body-level alignment (SequenceMatcher on
    # _struct_key bodies, not raw lines with +offset: prefixes).
    _ref_bodies = _offset_discrepancy_bodies(ref_lines)
    _our_bodies = _offset_discrepancy_bodies(our_lines)
    _sm = difflib.SequenceMatcher(
        None,
        [_struct_key(b) for b in _ref_bodies],
        [_struct_key(b) for b in _our_bodies],
        autojunk=False,
    )
    offset_discrepancies: list[dict] = []
    for _tag, _i1, _i2, _j1, _j2 in _sm.get_opcodes():
        if _tag not in ("equal", "replace"):
            continue
        if (_i2 - _i1) != (_j2 - _j1):
            continue  # unequal-length replace block: can't pair positionally
        # Dup-body guard applies ONLY to `replace` blocks. In an `equal` block
        # SequenceMatcher guarantees ref_key[i1+k] == cur_key[j1+k] for all k,
        # so position k <-> position k is the authoritative correspondence and
        # repeated keys cannot mispair (this is the matched-opcode case that
        # finds real struct-offset bugs). In a `replace` block instructions may
        # be reordered, so a repeated key CAN mispair -> skip the block.
        if _tag == "replace":
            _block_keys = [_struct_key(_ref_bodies[_i1 + _k]) for _k in range(_i2 - _i1)]
            if len(set(_block_keys)) != len(_block_keys):
                continue
        for _k in range(_i2 - _i1):
            _d = _paired_struct_offset_delta(_ref_bodies[_i1 + _k], _our_bodies[_j1 + _k])
            if _d:
                _d["ref_index"] = _i1 + _k
                _d["cur_index"] = _j1 + _k
                offset_discrepancies.append(_d)

    result = {"primary": primary, "reasons": reasons}
    if stack_frame_delta:
        result["stack_frame_delta"] = stack_frame_delta
    if stack_slot_localizer:
        result["stack_slot_localizer"] = stack_slot_localizer
    if inline_boundary_artifact:
        result["inline_boundary_artifact"] = inline_boundary_artifact
    if indexed_struct_pointer_materialization:
        result["indexed_struct_pointer_materialization"] = (
            indexed_struct_pointer_materialization
        )
    if register_allocation_guidance:
        result["register_allocation_guidance"] = register_allocation_guidance
    if bss_anchor_relocations:
        result["bss_anchor_relocations"] = bss_anchor_relocations
    if value_numbering_ceiling:
        result["value_numbering_ceiling"] = value_numbering_ceiling
    if backend_ceiling:
        result["backend_ceiling"] = {
            "subclass": backend_ceiling["subclass"],
            "confidence": backend_ceiling["confidence"],
        }
    result["structural_truth_gate"] = structural_truth_gate
    result["offset_discrepancies"] = offset_discrepancies
    return result


def is_effective_match(ref_asm: str, our_asm: str, classification: dict) -> bool:
    """Return whether the diff should be considered a successful match.

    The classification is computed after optional normalization, so it can
    identify instruction-identical output even when raw disassembly strings
    differ only in harmless tool presentation details.
    """
    effective_classifications = {
        "instruction-identical",
        "relocation-label-only",
    }
    return (
        ref_asm == our_asm
        or classification.get("primary") in effective_classifications
    )


def compute_structural_metrics(ref_lines: list[str], our_lines: list[str]) -> dict:
    """Metrics that capture *structural* closeness, independent of match%.

    These complement fuzzy_match_percent (which is byte-for-byte) by measuring
    how close the disassembly *shape* is. Useful when register/operand
    differences keep match% low even after a structural change brought the
    function closer to the true match.

    Returned:
      opcode_similarity (0.0-1.0): normalized similarity over the opcode
        sequence with operands/registers stripped. 1.0 means same opcodes in
        same order; 0.0 means nothing in common.
      line_delta (int): |expected_lines - current_lines|. 0 means same length.
      hunk_count (int): number of contiguous non-equal regions in the diff.
        Fewer hunks = more aligned structure.
    """
    import difflib

    ref_ops = _mnemonics(ref_lines)
    our_ops = _mnemonics(our_lines)
    if ref_ops or our_ops:
        opcode_similarity = difflib.SequenceMatcher(None, ref_ops, our_ops).ratio()
    else:
        opcode_similarity = 1.0

    line_delta = abs(len(ref_lines) - len(our_lines))

    sm = difflib.SequenceMatcher(None, ref_lines, our_lines)
    hunk_count = sum(1 for tag, *_ in sm.get_opcodes() if tag != "equal")

    return {
        "opcode_similarity": opcode_similarity,
        "line_delta": line_delta,
        "hunk_count": hunk_count,
    }


# Per-worktree cache of last-run metrics per function. Lives under build/
# (gitignored) so each worktree tracks its own progress independently.
HISTORY_DIR = ROOT / "build" / ".checkdiff-history"


def load_history(func_name: str) -> Optional[dict]:
    path = HISTORY_DIR / f"{func_name}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_history(func_name: str, snapshot: dict) -> None:
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        (HISTORY_DIR / f"{func_name}.json").write_text(json.dumps(snapshot))
    except OSError:
        pass  # non-fatal; history is a convenience, not a requirement


def _fmt_delta(current, prev, *, lower_is_better: bool, precision: int = 1) -> str:
    """Format an inline (↑/↓ N) delta vs prev, or "" if no prev or no change.

    For 'lower is better' metrics (line_delta, hunk_count), ↓ is green progress.
    For 'higher is better' metrics (match%, opcode similarity), ↑ is green.
    """
    if prev is None:
        return ""
    try:
        delta = current - prev
    except TypeError:
        return ""
    if delta == 0:
        return " ="
    arrow = "↓" if delta < 0 else "↑"
    mag = abs(delta)
    is_progress = (lower_is_better and delta < 0) or (not lower_is_better and delta > 0)
    marker = "" if is_progress else "  ⚠"
    if isinstance(current, float) or isinstance(prev, float):
        return f" ({arrow} {mag:.{precision}f}){marker}"
    return f" ({arrow} {mag}){marker}"


def render_metrics_block(
    fuzzy_pct: Optional[float],
    metrics: dict,
    prev: Optional[dict],
) -> str:
    """Multi-line block showing match% + structural metrics with deltas vs prev.

    Designed to make 'structurally improving but match% dropped' obvious so
    agents don't reflexively revert. Always shows all three structural
    metrics so the agent has the full picture.
    """
    lines = []
    if fuzzy_pct is not None:
        d = _fmt_delta(fuzzy_pct, (prev or {}).get("fuzzy_match_percent"), lower_is_better=False)
        lines.append(f"Match: {fuzzy_pct:.1f}%{d}")
    op_pct = metrics["opcode_similarity"] * 100
    op_d = _fmt_delta(op_pct, ((prev or {}).get("opcode_similarity") or 0) * 100 if prev else None, lower_is_better=False)
    lines.append(f"Opcode similarity: {op_pct:.1f}%{op_d}")
    ld_d = _fmt_delta(metrics["line_delta"], (prev or {}).get("line_delta"), lower_is_better=True, precision=0)
    lines.append(f"Line delta: {metrics['line_delta']}{ld_d}")
    hk_d = _fmt_delta(metrics["hunk_count"], (prev or {}).get("hunk_count"), lower_is_better=True, precision=0)
    lines.append(f"Hunks: {metrics['hunk_count']}{hk_d}")
    return "\n".join(lines)


def make_progress_note(
    fuzzy_pct: Optional[float],
    metrics: dict,
    prev: Optional[dict],
) -> Optional[str]:
    """If match% dropped but structural metrics improved, surface a nudge.

    Catches the 'don't reflexively revert' case: agents see match% go down
    and undo the change, even when the structure is now closer to the true
    match (register diffs are surface-level; structure is what unlocks the
    real match).
    """
    if not prev:
        return None
    prev_match = prev.get("fuzzy_match_percent")
    if prev_match is None or fuzzy_pct is None:
        return None
    op_now = metrics["opcode_similarity"]
    op_prev = prev.get("opcode_similarity", 0.0)
    hunks_now = metrics["hunk_count"]
    hunks_prev = prev.get("hunk_count", 1 << 30)
    line_now = metrics["line_delta"]
    line_prev = prev.get("line_delta", 1 << 30)

    if fuzzy_pct > prev_match + 0.01:
        opcode_drop = op_prev - op_now
        structural_regression = (
            opcode_drop >= 0.20
            and (hunks_now > hunks_prev or line_now > line_prev)
        )
        if structural_regression:
            return (
                "WARNING: match% rose, but opcode similarity collapsed and "
                "line/hunk shape regressed. Treat this as likely false "
                "progress; opcode similarity is the authoritative structural "
                "signal for this kind of instruction-removal change."
            )
        return None

    if fuzzy_pct >= prev_match - 0.01:  # not really a drop
        return None

    structural_progress = (
        op_now > op_prev + 0.005
        or hunks_now < hunks_prev
        or line_now < line_prev
    )
    if not structural_progress:
        return None
    return (
        "NOTE: match% dropped, but structure improved (opcode similarity ↑, "
        "fewer hunks, or smaller line delta). This is often progress toward "
        "the true match — don't reflexively revert. Read the full diff and "
        "decide whether the new structure looks closer to expected."
    )


def format_summary(
    func_name: str,
    *,
    matched: bool,
    fuzzy_pct: Optional[float],
    classification: dict,
) -> str:
    """Return a compact one-line status for scripts and quick probes."""
    pct_text = "unknown" if fuzzy_pct is None else f"{fuzzy_pct:.2f}"
    primary = classification.get("primary") or "unknown"
    match_text = str(matched).lower()
    fields = [
        f"function={func_name} "
        f"match={match_text}",
        f"match_percent={pct_text}",
        f"classification={primary}",
    ]
    truth_gate = classification.get("structural_truth_gate")
    if isinstance(truth_gate, dict):
        fields.append(
            "normalized_diff_lines="
            f"{truth_gate.get('normalized_diff_lines', 'unknown')}"
        )
        status = truth_gate.get("status")
        if status in {"structural-match", "near-zero-structural-diff"}:
            fields.append(f"truth={status}")
    pad_probe = classification.get("diagnostic_pad_stack")
    if pad_probe:
        fields.append(f"diagnostic_pad_stack={pad_probe.get('total_pad_stack_bytes')}")
        localizer = classification.get("stack_slot_localizer")
        reserved_low_spill = (
            localizer.get("reserved_low_spill_region")
            if isinstance(localizer, dict)
            else None
        )
        if reserved_low_spill:
            fields.append("source_guidance=reserved-low-spill-ceiling")
            fields.append("closability_tier=ceiling")
        else:
            fields.append("source_guidance=natural-frame-reservation")
    return " ".join(fields)


_REGISTER_TOKEN_RE = re.compile(r"\b[rf](?:[0-9]|[12][0-9]|3[01])\b")


def _normalize_register_tokens(text: str) -> str:
    return _REGISTER_TOKEN_RE.sub(lambda m: f"{m.group(0)[0]}N", text)


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    return singular if n == 1 else (plural or f"{singular}s")


def format_compact(
    func_name: str,
    *,
    matched: bool,
    fuzzy_pct: Optional[float],
    classification: dict,
    ref_lines: list[str],
    our_lines: list[str],
    max_examples: int = 4,
) -> str:
    """Return a compact multi-line diff summary for last-mile mismatches."""
    lines = [
        format_summary(
            func_name,
            matched=matched,
            fuzzy_pct=fuzzy_pct,
            classification=classification,
        )
    ]
    reasons = classification.get("reasons") or []
    if reasons:
        lines.append("reasons:")
        lines.extend(f"  - {reason}" for reason in reasons)

    primary = classification.get("primary")
    relocation_diffs = [
        (ref, cur)
        for ref, cur in zip(ref_lines, our_lines)
        if ref != cur and (_is_relocation_line(ref) or _is_relocation_line(cur))
    ]
    register_diffs = [
        (ref, cur)
        for ref, cur in zip(ref_lines, our_lines)
        if (
            ref != cur
            and not _is_relocation_line(ref)
            and not _is_relocation_line(cur)
            and _normalize_register_tokens(_asm_body(ref))
            == _normalize_register_tokens(_asm_body(cur))
        )
    ]

    lines.append("compact_diff:")
    if primary == "relocation-label-only" and relocation_diffs:
        n = len(relocation_diffs)
        lines.append(
            f"  relocation-only: {n} relocation annotation "
            f"{_plural(n, 'line')} {_plural(n, 'differs', 'differ')}"
        )
    elif register_diffs:
        n = len(register_diffs)
        lines.append(
            f"  register-only: {n} paired instruction "
            f"{_plural(n, 'line')} {_plural(n, 'differs', 'differ')} "
            f"only by register"
        )
        for ref, cur in register_diffs[:max_examples]:
            lines.append(f"    expected: {ref}")
            lines.append(f"    current:  {cur}")
        if len(register_diffs) > max_examples:
            lines.append(f"    ... {len(register_diffs) - max_examples} more")
    elif relocation_diffs:
        n = len(relocation_diffs)
        lines.append(
            f"  relocation-related: {n} paired "
            f"{_plural(n, 'line')} touch relocation annotations"
        )
    else:
        lines.append("  no compact grouping available; inspect full diff")
    lines.append("hint: rerun with --format side-by-side for full context")
    return "\n".join(lines)


def format_side_by_side(ref_lines: list[str], our_lines: list[str], width: int = 56) -> str:
    """Generate a side-by-side diff comparing expected (left) vs current (right)."""
    import difflib

    sm = difflib.SequenceMatcher(None, ref_lines, our_lines)
    output = []

    # Simple header
    output.append(f"{'EXPECTED':<{width}}    {'CURRENT':<{width}}")
    output.append("")

    def truncate(s: str, w: int) -> str:
        s = s.rstrip()
        if len(s) > w:
            return s[:w-3] + "..."
        return s

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for i in range(i2 - i1):
                left = truncate(ref_lines[i1 + i], width)
                right = truncate(our_lines[j1 + i], width)
                output.append(f"  {left:<{width}}    {right}")
        elif tag == 'replace':
            # Show replaced lines side by side
            max_lines = max(i2 - i1, j2 - j1)
            for i in range(max_lines):
                if i1 + i < i2:
                    left = truncate(ref_lines[i1 + i], width)
                    left_mark = "- "
                else:
                    left = ""
                    left_mark = "  "
                if j1 + i < j2:
                    right = truncate(our_lines[j1 + i], width)
                    right_mark = "+ "
                else:
                    right = ""
                    right_mark = "  "
                output.append(f"{left_mark}{left:<{width}}  {right_mark}{right}")
        elif tag == 'delete':
            for i in range(i2 - i1):
                left = truncate(ref_lines[i1 + i], width)
                output.append(f"- {left:<{width}}")
        elif tag == 'insert':
            for i in range(j2 - j1):
                right = truncate(our_lines[j1 + i], width)
                output.append(f"  {'':<{width}}  + {right}")

    return "\n".join(output)


def load_report_json(path=None) -> dict:
    """Load report.json with a short retry for concurrent partial reads."""
    report_path = REPORT_PATH if path is None else path
    attempts = max(1, REPORT_JSON_READ_RETRIES)
    for attempt in range(attempts):
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(REPORT_JSON_READ_RETRY_DELAY_SECONDS)
    return {}


def load_objdiff_json(path=None) -> dict:
    objdiff_path = OBJDIFF_CONFIG_PATH if path is None else path
    try:
        return json.loads(Path(objdiff_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_unit_name(name: str | None) -> str:
    return (name or "").removeprefix("main/").strip("/")


def resolve_objdiff_unit_paths(
    unit_name: str,
    objdiff_data: dict | None = None,
    *,
    repo_root: Path = ROOT,
) -> dict | None:
    """Resolve expected/current object paths from objdiff.json orientation.

    objdiff's ``target_path`` is the expected/reference object and
    ``base_path`` is the locally rebuilt current object. Keep that orientation
    explicit so normalized gates do not accidentally self-compare the target
    tree.
    """
    data = objdiff_data if objdiff_data is not None else load_objdiff_json()
    wanted = _normalize_unit_name(unit_name)
    for unit in data.get("units", []):
        if _normalize_unit_name(unit.get("name")) != wanted:
            continue
        target_path = unit.get("target_path")
        base_path = unit.get("base_path")
        if not target_path or not base_path:
            return None
        expected = Path(target_path)
        current = Path(base_path)
        if not expected.is_absolute():
            expected = repo_root / expected
        if not current.is_absolute():
            current = repo_root / current
        return {
            "expected_path": str(expected),
            "current_path": str(current),
            "unit": unit.get("name") or unit_name,
        }
    return None


def resolve_objdiff_function_paths(
    func_name: str,
    *,
    report_data: dict | None = None,
    objdiff_data: dict | None = None,
    repo_root: Path = ROOT,
) -> dict | None:
    report = report_data if report_data is not None else load_report_json()
    unit_name = None
    for unit in report.get("units", []):
        for function in unit.get("functions", []):
            if function.get("name") == func_name:
                unit_name = _normalize_unit_name(unit.get("name"))
                break
        if unit_name is not None:
            break
    if unit_name is None:
        return None
    return resolve_objdiff_unit_paths(
        unit_name,
        objdiff_data,
        repo_root=repo_root,
    )


def find_unit_for_function(func_name: str) -> Optional[str]:
    for unit in load_report_json().get("units", []):
        for function in unit.get("functions", []):
            if function.get("name") == func_name:
                return unit.get("name", "").removeprefix("main/")
    return None


def _ninja_build_edge_exists(target: str) -> Optional[bool]:
    """Return whether build.ninja has a build edge for target.

    ``None`` means build.ninja is unavailable, in which case callers should let
    Ninja report the underlying configuration problem itself.
    """
    build_ninja = ROOT / "build.ninja"
    try:
        lines = build_ninja.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    wanted = target.removeprefix("./")
    for line in lines:
        if not line.startswith("build "):
            continue
        outputs, sep, _ = line[len("build "):].partition(":")
        if not sep:
            continue
        if wanted in {output.removeprefix("./") for output in outputs.split()}:
            return True
    return False


def _format_missing_source_build_target_error(
    func_name: str,
    obj_path: str,
    source_obj: str,
) -> str:
    source_path = SRC_ROOT / f"{obj_path}.c"
    try:
        source_rel = source_path.relative_to(ROOT)
    except ValueError:
        source_rel = source_path

    if source_path.exists():
        return (
            f"error: no configured source build target for {func_name}: "
            f"{source_obj}\n"
            f"source file exists at {source_rel}, but build.ninja has no build "
            "rule for that object.\n"
            "declare the translation unit in configure.py, for example:\n"
            f'    Object(NonMatching, "{obj_path}.c"),\n'
            "then run python configure.py and retry checkdiff."
        )
    return (
        f"error: no configured source build target for {func_name}: "
        f"{source_obj}\n"
        f"expected source file {source_rel} is also missing."
    )


def missing_source_build_target_error(
    func_name: str,
    obj_path: str,
    source_obj: str,
) -> Optional[str]:
    edge_exists = _ninja_build_edge_exists(source_obj)
    if edge_exists is not False:
        return None
    return _format_missing_source_build_target_error(func_name, obj_path, source_obj)


def _depfile_dependencies(depfile: Path) -> list[Path]:
    """Parse a Make-style depfile and return existing repo-local deps."""
    try:
        text = depfile.read_text(errors="ignore")
    except OSError:
        return []
    text = text.replace("\\\n", " ")
    if ":" not in text:
        return []
    _, deps_text = text.split(":", 1)
    deps: list[Path] = []
    for raw in deps_text.split():
        token = raw.strip()
        if not token:
            continue
        path = Path(token)
        if not path.is_absolute():
            path = ROOT / path
        try:
            resolved = path.resolve()
            resolved.relative_to(ROOT.resolve())
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            deps.append(resolved)
    return deps


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return "missing"


def _dependency_context_digest(source: Path, obj_path: str) -> str:
    depfile = ROOT / "build" / "GALE01" / "src" / f"{obj_path}.d"
    paths = {source.resolve()}
    paths.update(_depfile_dependencies(depfile))
    rows = []
    for path in sorted(paths, key=str):
        try:
            rel = path.relative_to(ROOT.resolve())
        except ValueError:
            rel = path
        rows.append(f"{rel}:{_file_digest(path)}")
    payload = "\n".join(rows)
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:12]


def _with_dependency_context(fp: "Fingerprint", source: Path, obj_path: str) -> "Fingerprint":
    context = _dependency_context_digest(source, obj_path)
    raw = hashlib.sha1(f"{fp.raw}:ctx:{context}".encode()).hexdigest()[:12]
    norm = hashlib.sha1(f"{fp.normalized}:ctx:{context}".encode()).hexdigest()[:12]
    return Fingerprint(raw=raw, normalized=norm, body=fp.body)


def fingerprint_for_function(func_name: str, obj_path: str) -> Optional["Fingerprint"]:
    """Compute the fingerprint for `func_name` from its source file.

    `obj_path` is the unit path returned by find_unit_for_function (e.g.
    "melee/mn/sample"). The final hash includes the function body plus
    repo-local TU/dependency content, so header, prototype, and file-local
    type layout changes do not masquerade as same-source repeats.
    Returns None if fingerprinting is disabled, the source file is missing,
    or the function can't be extracted.
    """
    if not _FINGERPRINT_AVAILABLE:
        return None
    source = SRC_ROOT / f"{obj_path}.c"
    if not source.exists():
        return None
    fp = fingerprint_for(source, func_name)
    if fp is None:
        return None
    return _with_dependency_context(fp, source, obj_path)



MATCH_TOLERANCE = 0.1  # match% delta below which we treat two attempts as identical


def classify_attempt(prior: Optional[dict], current_match: float) -> str:
    """Three-way classifier: 'novel', 'repeat', or 'divergent'.

    Used by main() to decide between increment_replay (repeat),
    record_attempt with a fresh entry (novel or divergent), and which
    banner — if any — to emit.
    """
    if prior is None:
        return "novel"
    prior_match = float(prior.get("match_percent", 0.0))
    if abs(current_match - prior_match) <= MATCH_TOLERANCE:
        return "repeat"
    return "divergent"


def format_banner(branch: str, func_name: str, prior: dict, *,
                  current_match: float,
                  distinct_match_count: int = 1) -> str:
    """Build the [REPEAT] / [DIVERGENT REPEAT] banner text.

    `distinct_match_count` is only meaningful for the divergent branch:
    it's the number of distinct match%s recorded for this fingerprint
    (including the current one), derived by the caller from the ledger.
    """
    if branch == "repeat":
        header = "[REPEAT (semantic)]" if prior.get("match_type") == "norm" else "[REPEAT]"
        next_count_ordinal = _ordinal(int(prior.get("replay_count", 0)) + 2)
        prior_outcome = prior.get("outcome", "")
        prior_class = prior.get("classification", "")
        return (
            f"{header} this source matches attempt #{prior.get('index', '?')} for {func_name}\n"
            f"  - prior match%:    {prior.get('match_percent', 0):.1f}   "
            f"(class={prior_class}, outcome={prior_outcome})\n"
            f"  - current match%:  {current_match:.1f}   (same — verified)\n"
            f"  - prior agent:     {prior.get('agent_id', '?')}, "
            f"{prior.get('timestamp_utc', '')}\n"
            f"  - prior note:      \"{prior.get('note', '')}\"\n"
            f"  - repeat count:    this is the {next_count_ordinal} time at this fingerprint\n"
        )
    elif branch == "divergent":
        prior_class = prior.get("classification", "")
        return (
            f"[DIVERGENT REPEAT] same function-body/dependency fingerprint as "
            f"attempt #{prior.get('index', '?')} but new outcome\n"
            f"  - prior match%:    {prior.get('match_percent', 0):.1f}   "
            f"(class={prior_class})\n"
            f"  - current match%:  {current_match:.1f}   ← changed; external state differs\n"
            f"  - prior agent:     {prior.get('agent_id', '?')}, "
            f"{prior.get('timestamp_utc', '')}\n"
            f"  - prior note:      \"{prior.get('note', '')}\"\n"
            f"  - this fingerprint has produced {distinct_match_count} distinct match%s historically\n"
            f"  - note: dependency/header/source context may have changed; "
            f"rerun after a fresh build if this looks stale\n"
        )
    return ""


def emit_attempt_banner(banner: str) -> None:
    """Print repeat diagnostics after flushing diff output.

    When stdout is a pipe it is block-buffered. Flushing before stderr keeps
    repeat banners from visually landing in the middle of a disassembly line
    when callers merge both streams for paging or range filtering.
    """
    if not banner:
        return
    try:
        sys.stdout.flush()
    except Exception:
        pass
    print(banner, file=sys.stderr, flush=True)


def _count_distinct_match_percents(
    function_name: str,
    fingerprint: str,
    *,
    include_pending: bool = False,
) -> int:
    """Count distinct match%s recorded for this (function, fingerprint).

    By default (include_pending=False), called AFTER the divergent attempt
    is recorded — the new match% is already in the ledger.

    Set include_pending=True for callers (like --dry-run) that haven't
    recorded the current attempt and need it reflected in the count.

    Returns at least 1 (the current attempt counts even if the ledger is
    empty or missing).
    """
    from src.cli.tracking import load_attempt_ledger
    ledger = load_attempt_ledger()
    entry = ledger.get("functions", {}).get(function_name, {})
    matches = {
        round(a.get("match_percent", 0), 1)
        for a in entry.get("attempts", [])
        if a.get("fingerprint") == fingerprint
    }
    return max(1, len(matches) + (1 if include_pending else 0))


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 30 -> '30th'."""
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def record_post_build_attempt(
    *,
    func_name: str,
    obj_path: str,
    fp: "Fingerprint",
    prior_attempt: Optional[dict],
    c_file: Path,
    current_match: float,
    source_code: str = "",
    diff: str = "",
    verdict: str = "",
) -> str:
    """Apply the dedup-on-write policy and return a banner string (or "").

    Called once per successful checkdiff run. The caller is responsible
    for printing the returned banner; this function only mutates the
    ledger and computes the message.
    """
    if fp is None:
        return ""
    # Clamp to [0, 100] — record_attempt raises ValueError outside that
    # range, and we'd rather degrade silently on a corrupt report.json
    # than kill checkdiff.
    clamped_match = max(0.0, min(100.0, float(current_match)))
    source_file = str(c_file.relative_to(ROOT)) if c_file.is_absolute() else str(c_file)

    branch = classify_attempt(prior_attempt, clamped_match)

    if branch == "novel":
        record_attempt(
            func_name,
            match_percent=clamped_match,
            outcome="neutral",
            fingerprint=fp.raw,
            fingerprint_norm=fp.normalized,
            source_file=source_file,
            source_code=source_code,
            diff=diff,
            verdict=verdict,
        )
        return ""

    if branch == "repeat":
        increment_replay(func_name, attempt_index=prior_attempt["index"])
        return format_banner("repeat", func_name, prior_attempt,
                             current_match=clamped_match)

    # divergent
    record_attempt(
        func_name,
        match_percent=clamped_match,
        outcome="neutral",
        fingerprint=fp.raw,
        fingerprint_norm=fp.normalized,
        source_file=source_file,
        source_code=source_code,
        diff=diff,
        verdict=verdict,
    )
    distinct = _count_distinct_match_percents(func_name, fp.raw)
    return format_banner("divergent", func_name, prior_attempt,
                         current_match=clamped_match,
                         distinct_match_count=distinct)


def get_fuzzy_match_percent(func_name: str) -> Optional[float]:
    """Get the fuzzy_match_percent for a function from report.json."""
    for unit in load_report_json().get("units", []):
        for function in unit.get("functions", []):
            if function.get("name") == func_name:
                return function.get("fuzzy_match_percent")
    return None


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("function", help="Function name")
    ap.add_argument("--no-tty", action="store_true",
                    help="Force non-interactive output (auto-detected if no TTY)")
    ap.add_argument(
        "--format",
        choices=["plain", "side-by-side", "json", "summary", "compact"],
        default="side-by-side",
        help="Output format when using --no-tty (default: side-by-side)",
    )
    ap.add_argument(
        "--summary",
        dest="format",
        action="store_const",
        const="summary",
        help="Compact one-line output: function, match bool, match percent, classification",
    )
    ap.add_argument(
        "--compact",
        dest="format",
        action="store_const",
        const="compact",
        help="Compact grouped output for reloc-only/register-only last-mile diffs",
    )
    ap.add_argument("--no-build", action="store_true",
                    help="Skip the ninja rebuild step and diff the .o as-is. "
                         "Use this when the .o has been post-processed externally "
                         "(e.g. by `melee-agent debug name-magic`).")
    ap.add_argument("--pcdump", type=Path,
                    help="Optional mwcc_debug pcdump.txt for the current build. "
                         "When stack-slot-localizer fires, checkdiff maps the "
                         "shifted r1 slot back to likely MWCC virtual/IG roots.")
    ap.add_argument("--build-timeout", type=float,
                    default=DEFAULT_BUILD_TIMEOUT_SECONDS,
                    help="Timeout in seconds for each ninja build/report step "
                         f"(default: {DEFAULT_BUILD_TIMEOUT_SECONDS}; override "
                         "with CHECKDIFF_BUILD_TIMEOUT).")
    ap.add_argument("--normalize-reloc", dest="normalize_reloc", action="store_true",
                    default=True,
                    help="Round reloc-line offsets down to the containing "
                         "4-byte instruction. Treats relocations on the "
                         "immediate halfword (+2) as belonging to the same "
                         "instruction so opcode-identical functions aren't "
                         "marked mismatched on the +2 SDA21 quirk, and "
                         "canonicalizes zero-size section anchors to named "
                         "globals at the same object-file offset. (default: on)")
    ap.add_argument("--no-normalize-reloc", dest="normalize_reloc", action="store_false",
                    help="Disable reloc-offset normalization (emit reloc "
                         "lines exactly as the disassembler produced them).")
    ap.add_argument("--no-name-magic", dest="name_magic", action="store_false",
                    default=True,
                    help="Disable the transparent name-magic auto-rename "
                         "that rewrites anonymous .sdata2 @N symbols in the "
                         "freshly-built .o to their production-symbol names "
                         "via the matching ./build/GALE01/obj/<unit>.o. "
                         "Pass this to debug the rename behavior itself or "
                         "to see raw @N relocation names in the diff. "
                         "(default: rename enabled)")
    ap.add_argument("--no-fingerprint", dest="fingerprint", action="store_false",
                    default=True,
                    help="Disable source-state fingerprinting + auto-record + "
                         "repeat detection. Also disabled by env var "
                         "CHECKDIFF_NO_FINGERPRINT=1.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read-only fingerprint preview: skips ninja and "
                         "all ledger writes, but reads cached report.json "
                         "and emits the [REPEAT]/[DIVERGENT REPEAT] banner "
                         "that a real run would emit. Exits 3 if report.json "
                         "is missing.")
    return ap


def fingerprint_disabled() -> bool:
    """True if the CHECKDIFF_NO_FINGERPRINT env var is set to a truthy value."""
    return os.environ.get("CHECKDIFF_NO_FINGERPRINT", "") in ("1", "true", "yes")


def _fingerprint_tracking_enabled(args) -> bool:
    """True when this invocation should read/write source-state attempts."""
    return bool(getattr(args, "fingerprint", False)) and not bool(
        getattr(args, "no_build", False)
    )


def main() -> int:
    args = _build_arg_parser().parse_args()
    if fingerprint_disabled():
        args.fingerprint = False

    guard_error = expected_worktree_guard_error()
    if guard_error is not None:
        print(guard_error, file=sys.stderr)
        return 2

    if args.dry_run:
        if not REPORT_PATH.exists():
            print(f"--dry-run: {REPORT_PATH} does not exist", file=sys.stderr)
            return 3
        func_name = args.function
        obj_path = find_unit_for_function(func_name)
        if obj_path is None:
            print(f"--dry-run: function '{func_name}' not in report.json",
                  file=sys.stderr)
            return 3
        if _fingerprint_tracking_enabled(args) and _FINGERPRINT_AVAILABLE:
            fp = fingerprint_for_function(func_name, obj_path)
            if fp is not None:
                prior = find_attempt_by_fp(func_name, fp.raw, fp.normalized)
                current = max(0.0, min(100.0, get_fuzzy_match_percent(func_name) or 0.0))
                branch = classify_attempt(prior, current)
                if branch == "repeat":
                    emit_attempt_banner(format_banner(
                        "repeat",
                        func_name,
                        prior,
                        current_match=current,
                    ))
                elif branch == "divergent":
                    distinct = _count_distinct_match_percents(
                        func_name, fp.raw, include_pending=True
                    )
                    emit_attempt_banner(format_banner(
                        "divergent",
                        func_name,
                        prior,
                        current_match=current,
                        distinct_match_count=distinct,
                    ))
        return 0

    # Auto-detect TTY - use non-interactive mode if no TTY available
    if not sys.stdout.isatty():
        args.no_tty = True
    # Machine-readable/compact formats always use the non-interactive path
    # (TTY would only produce objdiff-cli's interactive diff).
    if args.format in {"json", "summary", "compact"}:
        args.no_tty = True

    func_name = args.function

    # locate object file by parsing report.json
    obj_path = find_unit_for_function(func_name)
    if obj_path is None:
        print(f"error: could not find function '{func_name}' in report.json", file=sys.stderr)
        return 1

    if args.no_build and args.fingerprint and _FINGERPRINT_AVAILABLE:
        print(
            "[checkdiff] fingerprint tracking disabled for --no-build; "
            "object state may be externally managed",
            file=sys.stderr,
        )

    ref_obj = f"./build/GALE01/obj/{obj_path}.o"
    our_obj = f"./build/GALE01/src/{obj_path}.o"
    c_file = SRC_ROOT / f"{obj_path}.c"
    if not args.no_build:
        source_target_error = missing_source_build_target_error(
            func_name,
            obj_path,
            our_obj,
        )
        if source_target_error is not None:
            print(source_target_error, file=sys.stderr)
            return 1

    lock_handle = (
        acquire_checkdiff_lock(obj_path)
        if should_acquire_checkdiff_lock(args)
        else None
    )
    _ = lock_handle  # Keep the lock file alive until process exit.

    # Pre-build phase: compute fingerprint and look up prior attempt.
    fp = None
    prior_attempt = None
    if _fingerprint_tracking_enabled(args) and _FINGERPRINT_AVAILABLE:
        fp = fingerprint_for_function(func_name, obj_path)
        if fp is not None:
            prior_attempt = find_attempt_by_fp(func_name, fp.raw, fp.normalized)

    # fix includes (optional - lukechampine's repo has this)
    fix_includes = ROOT / "tools" / "fix_includes.py"
    if fix_includes.exists():
        result = subprocess.run(
            [sys.executable, str(fix_includes), str(c_file)],
            cwd=ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            print("fix_includes.py failed:", file=sys.stderr)
            print(result.stderr.decode(), file=sys.stderr)
            return 1

    # build
    if not args.no_build:
        result = _run_build_command(
            ["ninja", our_obj],
            timeout=args.build_timeout,
            hint=(
                "retry with --no-build after a successful manual rebuild, "
                "or raise --build-timeout"
            ),
        )
        if result.returncode != 0:
            print("ninja failed:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

        # Regenerate report.json to get fresh fuzzy_match_percent
        # This is needed because the VS Code extension relies on accurate match percentages
        result = _run_build_command(
            ["ninja", "build/GALE01/report.json"],
            timeout=args.build_timeout,
            hint=(
                "retry with --no-build after a successful manual rebuild, "
                "or raise --build-timeout"
            ),
        )
        if result.returncode != 0:
            print(
                format_subprocess_failure(
                    "warning: failed to regenerate report.json",
                    result,
                ),
                file=sys.stderr,
            )
    else:
        # --no-build: caller has post-processed the .o; just verify it exists.
        if not (ROOT / our_obj.lstrip("./")).exists():
            print(f"error: --no-build given but {our_obj} not found; "
                  f"build it first (or omit --no-build)", file=sys.stderr)
            return 1

    # Transparently rename anonymous .sdata2 @N magic constants in the
    # freshly-built .o to their production-symbol names. Idempotent and
    # opt-out via --no-name-magic. Mutating the .o under build/GALE01/src/
    # is safe (it's rebuilt on demand and ignored by git).
    if args.name_magic:
        source_o_abs = ROOT / our_obj.lstrip("./")
        target_o_abs = ROOT / ref_obj.lstrip("./")
        apply_name_magic_if_available(source_o_abs, target_o_abs)

    # diff
    snapshot_diff = ""
    snapshot_verdict = ""
    if args.no_tty:
        # Use objdump or dtk + diff for non-interactive output (works without TTY)
        import re

        disasm_type, disasm_path = ensure_disassembler()

        def get_asm_with_objdump(
            obj_path: str,
            func: str,
            normalize: bool = True,
            tool_path: Path | str = disasm_path,
        ) -> str:
            """Extract disassembly for a function using objdump."""
            result = subprocess.run(
                [str(tool_path), "-d", "-r", obj_path],
                cwd=ROOT, capture_output=True, text=True
            )
            lines = result.stdout.split("\n")
            in_func = False
            output = []
            func_base_addr = None
            for line in lines:
                if f"<{func}>:" in line:
                    in_func = True
                    # Extract base address from function header (e.g., "00000180 <func>:")
                    match = re.match(r"^\s*([0-9a-f]+)\s+<", line)
                    if match:
                        func_base_addr = int(match.group(1), 16)
                    if normalize:
                        output.append(f"<{func}>:")
                    else:
                        output.append(line)
                elif in_func:
                    if line and not line.startswith(" ") and ":" in line and "<" in line:
                        break  # start of next function
                    if normalize and line.strip():
                        # Extract address and compute relative offset
                        addr_match = re.match(r"^\s*([0-9a-f]+):\s*", line)
                        if addr_match and func_base_addr is not None:
                            addr = int(addr_match.group(1), 16)
                            rel_offset = addr - func_base_addr
                            # Strip address, add relative offset prefix
                            rest = re.sub(r"^\s*[0-9a-f]+:\s*", "", line)
                            # Normalize branch targets (e.g., "2460 <func+0x34>" -> "<func+0x34>")
                            rest = re.sub(r"\b[0-9a-f]+ (<[^>]+>)", r"\1", rest)
                            output.append(f"+{rel_offset:03x}: {rest}")
                        else:
                            # Fallback: just normalize without offset
                            normalized = re.sub(r"^\s*[0-9a-f]+:\s*", "  ", line)
                            normalized = re.sub(r"\b[0-9a-f]+ (<[^>]+>)", r"\1", normalized)
                            output.append(normalized)
                    else:
                        output.append(line)
            return "\n".join(output)

        def get_asm_with_dtk(
            obj_path: str,
            func: str,
            normalize: bool = True,
            tool_path: Path | str = disasm_path,
        ) -> str:
            """Extract disassembly for a function using dtk."""
            with tempfile.TemporaryDirectory() as tmpdir:
                asm_file = Path(tmpdir) / "disasm.s"
                result = subprocess.run(
                    [str(tool_path), "elf", "disasm", obj_path, str(asm_file)],
                    cwd=ROOT, capture_output=True, text=True
                )
                if result.returncode != 0 or not asm_file.exists():
                    return ""

                asm_content = asm_file.read_text()

            # Parse dtk output format to find the function. Older dtk emitted
            # "func_name:" labels; current dtk emits ".fn func_name, global"
            # blocks with address comments before each instruction.
            lines = asm_content.split("\n")
            in_func = False
            output = []
            instr_offset = 0  # Track offset (each PPC instruction is 4 bytes)

            for line in lines:
                stripped = line.strip()
                is_fn_start = (
                    stripped == f"{func}:"
                    or stripped.startswith(f".fn {func},")
                    or stripped == f".fn {func}"
                )
                if is_fn_start:
                    in_func = True
                    instr_offset = 0
                    if normalize:
                        output.append(f"<{func}>:")
                    else:
                        output.append(line)
                elif in_func:
                    # End of function: .endfn, another .fn, or section directive.
                    if (
                        stripped.startswith(".endfn")
                        or stripped.startswith(".fn ")
                        or stripped.startswith(".section")
                    ):
                        break
                    if not stripped:
                        continue
                    if stripped.endswith(":"):
                        continue
                    if normalize:
                        body = re.sub(r"^/\*\s*[^*]*\*/\s*", "", stripped)
                        if body and not body.startswith("."):  # Skip directives
                            output.append(f"+{instr_offset:03x}: {body}")
                            instr_offset += 4  # PPC instructions are 4 bytes
                    elif stripped:
                        output.append(line)

            return "\n".join(output)

        def get_asm_pair(
            kind: str,
            tool_path: Path | str,
        ) -> tuple[str, str]:
            if kind == "objdump":
                get_asm = get_asm_with_objdump
            else:
                get_asm = get_asm_with_dtk
            return (
                get_asm(str(ROOT / ref_obj), func_name, tool_path=tool_path),
                get_asm(str(ROOT / our_obj), func_name, tool_path=tool_path),
            )

        ref_asm, our_asm = get_asm_pair(disasm_type, disasm_path)
        if (not ref_asm or not our_asm) and disasm_type == "objdump":
            try:
                dtk_path = find_dtk() or download_dtk(TOOLS_CACHE_DIR / "dtk")
            except Exception:
                dtk_path = None
            if dtk_path is not None:
                fallback_ref_asm, fallback_our_asm = get_asm_pair("dtk", dtk_path)
                if fallback_ref_asm and fallback_our_asm:
                    print(
                        "[checkdiff] objdump did not extract requested "
                        "function; fell back to dtk",
                        file=sys.stderr,
                    )
                    ref_asm, our_asm = fallback_ref_asm, fallback_our_asm

        if not ref_asm:
            print(f"error: could not find {func_name} in reference object", file=sys.stderr)
            return 1
        if not our_asm:
            print(f"error: could not find {func_name} in compiled object", file=sys.stderr)
            return 1

        # Simple side-by-side or unified diff
        import difflib
        ref_lines = ref_asm.split("\n")
        our_lines = our_asm.split("\n")
        if args.normalize_reloc:
            ref_lines = normalize_reloc_line_offsets(ref_lines)
            our_lines = normalize_reloc_line_offsets(our_lines)
            ref_obj_path = ROOT / ref_obj.lstrip("./")
            our_obj_path = ROOT / our_obj.lstrip("./")
            ref_lines = normalize_section_anchor_references(
                ref_lines,
                collect_section_anchor_aliases(ref_obj_path, our_obj_path),
            )
            our_lines = normalize_section_anchor_references(
                our_lines,
                collect_section_anchor_aliases(our_obj_path, ref_obj_path),
            )
            sdata2_value_aliases = collect_sdata2_value_relocation_aliases(
                ref_obj_path,
                our_obj_path,
            )
            ref_lines = normalize_sdata2_value_relocation_aliases(
                ref_lines,
                sdata2_value_aliases,
            )
            our_lines = normalize_sdata2_value_relocation_aliases(
                our_lines,
                sdata2_value_aliases,
            )
        classification = classify_asm_diff(ref_lines, our_lines)
        objdiff_paths = resolve_objdiff_function_paths(func_name)
        if objdiff_paths and isinstance(
            classification.get("structural_truth_gate"), dict
        ):
            classification["structural_truth_gate"]["object_paths"] = objdiff_paths
        source_text_for_bridge = None
        if args.pcdump is not None and c_file.is_file():
            try:
                source_text_for_bridge = c_file.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                source_text_for_bridge = None
        add_stack_slot_pcdump_bridge(
            classification,
            function=func_name,
            pcdump_path=args.pcdump,
            source_text=source_text_for_bridge,
            source_file=(
                str(c_file.relative_to(ROOT))
                if c_file.is_absolute() else str(c_file)
            ),
        )
        add_pad_stack_probe_guidance(
            classification,
            detect_diagnostic_pad_stack_in_source(c_file, func_name),
        )
        matched = is_effective_match(ref_asm, our_asm, classification)
        snapshot_verdict = classification.get("primary") or ""

        if args.no_build:
            # report.json was not regenerated for --no-build. The object diff
            # below is fresh, but the cached fuzzy_match_percent can describe a
            # different prior build, so suppress it instead of publishing a
            # misleading headline percentage.
            fuzzy_pct = None
            fuzzy_pct_source = "suppressed_stale_report_no_build"
        else:
            fuzzy_pct = get_fuzzy_match_percent(func_name)
            fuzzy_pct_source = "report_json"
        metrics = compute_structural_metrics(ref_lines, our_lines)
        prev_metrics = load_history(func_name)
        progress_note = make_progress_note(fuzzy_pct, metrics, prev_metrics)
        snapshot = {
            "fuzzy_match_percent": fuzzy_pct,
            **metrics,
            "matched": matched,
        }
        save_history(func_name, snapshot)
        snapshot_diff = format_compact(
            func_name,
            matched=matched,
            fuzzy_pct=fuzzy_pct,
            classification=classification,
            ref_lines=ref_lines,
            our_lines=our_lines,
        )

        if args.format == "json":
            import json as json_mod
            diff_data = {
                "function": func_name,
                "reference_lines": len(ref_lines),
                "current_lines": len(our_lines),
                "match": matched,
                "classification": classification,
                "fuzzy_match_percent": fuzzy_pct,
                "fuzzy_match_percent_source": fuzzy_pct_source,
                "structural": metrics,
                "previous_run": prev_metrics,
                "progress_note": progress_note,
                "target_asm": ref_lines,
                "current_asm": our_lines,
                "diff": list(difflib.unified_diff(ref_lines, our_lines,
                    fromfile="expected", tofile="current", lineterm=""))
            }
            print(json_mod.dumps(diff_data, indent=2))
            result = subprocess.CompletedProcess([], 0 if matched else 1)
        elif args.format == "summary":
            print(format_summary(
                func_name,
                matched=matched,
                fuzzy_pct=fuzzy_pct,
                classification=classification,
            ))
            result = subprocess.CompletedProcess([], 0 if matched else 1)
        elif args.format == "compact":
            print(snapshot_diff)
            result = subprocess.CompletedProcess([], 0 if matched else 1)
        elif args.format == "side-by-side":
            # Side-by-side diff (better for agents to understand)
            if matched:
                print(f"--- MATCH: {func_name} matches! ---")
                pad_diag = format_pad_stack_probe_diagnostic(classification)
                if pad_diag:
                    print(pad_diag)
                result = subprocess.CompletedProcess([], 0)
            else:
                print(f"Function: {func_name}")
                print(render_metrics_block(fuzzy_pct, metrics, prev_metrics))
                if progress_note:
                    print(progress_note)
                print(f"Classification: {classification['primary']}")
                for reason in classification["reasons"]:
                    print(f"  - {reason}")
                print()
                print(format_side_by_side(ref_lines, our_lines))
                print(f"\n--- MISMATCH: {func_name} does not match ---")
                print("\nLegend: '-' = in expected only (missing), '+' = in current only (extra)")
                result = subprocess.CompletedProcess([], 1)
        else:
            # Plain unified diff
            diff = difflib.unified_diff(ref_lines, our_lines,
                fromfile="expected", tofile="current", lineterm="")
            diff_output = "\n".join(diff)
            if diff_output:
                print(diff_output)
                stack_diag = format_stack_frame_diagnostic(classification)
                if stack_diag:
                    print()
                    print(stack_diag)
                pad_diag = format_pad_stack_probe_diagnostic(classification)
                if pad_diag and pad_diag != stack_diag:
                    print()
                    print(pad_diag)
                print(f"\n--- MISMATCH: {func_name} does not match ---")
                result = subprocess.CompletedProcess([], 1)
            else:
                print(f"--- MATCH: {func_name} matches! ---")
                pad_diag = format_pad_stack_probe_diagnostic(classification)
                if pad_diag:
                    print(pad_diag)
                result = subprocess.CompletedProcess([], 0)
    else:
        result = subprocess.run(
            [
                str(OBJDIFF_CLI), "diff",
                "-c", "functionRelocDiffs=none",
                "-1", ref_obj,
                "-2", our_obj,
                func_name,
            ],
            cwd=ROOT,
        )

    # kill wine-preloader so we don't eat the user's battery life
    subprocess.run(["killall", "wine-preloader"], capture_output=True)

    # Post-build: dedup-on-write + banner.
    if _fingerprint_tracking_enabled(args) and _FINGERPRINT_AVAILABLE and fp is not None:
        current_match = get_fuzzy_match_percent(func_name) or 0.0
        try:
            snapshot_source = c_file.read_text()
        except OSError:
            snapshot_source = ""
        banner = record_post_build_attempt(
            func_name=func_name, obj_path=obj_path, fp=fp,
            prior_attempt=prior_attempt, c_file=c_file,
            current_match=current_match,
            source_code=snapshot_source,
            diff=snapshot_diff,
            verdict=snapshot_verdict,
        )
        if banner:
            emit_attempt_banner(banner)

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
