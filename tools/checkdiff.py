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
import hashlib
import json
import os
import platform
import re
import shutil
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
SRC_ROOT = ROOT / "src"
DEFAULT_BUILD_TIMEOUT_SECONDS = int(os.environ.get("CHECKDIFF_BUILD_TIMEOUT", "300"))

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


# Matches the normalized offset prefix produced by get_asm_with_objdump/dtk,
# e.g. "+0c0: " or "+042: ". The offset is hex, variable-width (3+ digits).
_NORMALIZED_OFFSET_RE = re.compile(r"^\+([0-9a-fA-F]+):(\s)")
_SECTION_ANCHOR_NAME_RE = re.compile(r"^\.\.\.[A-Za-z0-9_$.]+\.\d+$")
_SECTION_ANCHOR_TOKEN_CHARS = r"A-Za-z0-9_$."


def _is_section_anchor_symbol(name: str) -> bool:
    return bool(_SECTION_ANCHOR_NAME_RE.match(name))


def collect_section_anchor_aliases(obj_path: Path) -> dict[str, str]:
    """Map local zero-size section anchors to co-located global objects.

    MWCC/dtk can emit a local symbol such as ``...data.0`` at the same
    ``.data`` offset as a real global object, then show ADDR16_HA/LO relocs
    against that local anchor. The linker resolves both to the same address,
    so checkdiff should canonicalize the anchor to the named global before
    comparing disassembly.
    """
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return {}

    try:
        with obj_path.open("rb") as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return {}

            anchors_by_loc: dict[tuple[int, int], list[str]] = {}
            globals_by_loc: dict[tuple[int, int], list[str]] = {}
            for sym in symtab.iter_symbols():
                name = sym.name
                shndx = sym["st_shndx"]
                if not name or not isinstance(shndx, int):
                    continue
                loc = (shndx, int(sym["st_value"]))
                info = sym["st_info"]
                bind = info["bind"]
                sym_type = info["type"]
                size = int(sym["st_size"])

                if (
                    bind == "STB_LOCAL"
                    and size == 0
                    and _is_section_anchor_symbol(name)
                ):
                    anchors_by_loc.setdefault(loc, []).append(name)
                elif (
                    bind == "STB_GLOBAL"
                    and sym_type == "STT_OBJECT"
                    and size > 0
                    and not _is_section_anchor_symbol(name)
                ):
                    globals_by_loc.setdefault(loc, []).append(name)
    except (OSError, KeyError, TypeError, ValueError, ELFError):
        return {}

    aliases: dict[str, str] = {}
    for loc, anchors in anchors_by_loc.items():
        globals_at_loc = globals_by_loc.get(loc)
        if not globals_at_loc:
            continue
        replacement = globals_at_loc[0]
        for anchor in anchors:
            aliases[anchor] = replacement
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
        "expected_frame_size": expected_frame,
        "current_frame_size": current_frame,
        "frame_growth": frame_growth,
    }


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
    )


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
    message = format_pad_stack_probe_diagnostic(classification)
    if not message:
        return
    reasons = classification.setdefault("reasons", [])
    if message not in reasons:
        reasons.append(message)


def classify_asm_diff(ref_lines: list[str], our_lines: list[str]) -> dict:
    """Best-effort classification to help agents avoid chasing false leads."""
    if ref_lines == our_lines:
        return {
            "primary": "instruction-identical",
            "reasons": ["normalized disassembly is identical"],
        }

    if _strip_relocation_lines(ref_lines) == _strip_relocation_lines(our_lines):
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

    if len(ref_lines) != len(our_lines):
        reasons.append(f"line count differs: expected {len(ref_lines)}, current {len(our_lines)}")

    if ref_mnemonics == our_mnemonics:
        reasons.append("opcode sequence matches; differences are operands, registers, labels, or offsets")
        primary = "operand-register-or-offset"
    else:
        primary = "instruction-sequence"

    if len(ref_lines) != len(our_lines) and branch_shape_differs:
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
        reasons.append("call shape differs; check prototypes, return types, and inline boundaries")
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
    if likely_register_diffs:
        reasons.append(f"{likely_register_diffs} differing paired lines look register-only after normalization")
        if primary == "operand-register-or-offset":
            primary = "register-allocation"

    if inline_boundary_artifact:
        calls = ", ".join(inline_boundary_artifact["missing_ref_calls"])
        reasons.append(
            f"reference calls {calls} but current omits that call and is larger; "
            "likely wibo/local compiler inlined locally across an inline boundary"
        )
        primary = "inline-boundary-toolchain-artifact"

    if not reasons:
        reasons.append("differences require direct inspection")

    result = {"primary": primary, "reasons": reasons}
    if stack_frame_delta:
        result["stack_frame_delta"] = stack_frame_delta
    if stack_slot_localizer:
        result["stack_slot_localizer"] = stack_slot_localizer
    if inline_boundary_artifact:
        result["inline_boundary_artifact"] = inline_boundary_artifact
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
    if fuzzy_pct >= prev_match - 0.01:  # not really a drop
        return None
    op_now = metrics["opcode_similarity"]
    op_prev = prev.get("opcode_similarity", 0.0)
    hunks_now = metrics["hunk_count"]
    hunks_prev = prev.get("hunk_count", 1 << 30)
    line_now = metrics["line_delta"]
    line_prev = prev.get("line_delta", 1 << 30)

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
    pad_probe = classification.get("diagnostic_pad_stack")
    if pad_probe:
        fields.append(f"diagnostic_pad_stack={pad_probe.get('total_pad_stack_bytes')}")
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


def find_unit_for_function(func_name: str) -> Optional[str]:
    with REPORT_PATH.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return unit.get("name", "").removeprefix("main/")
    return None


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
    with REPORT_PATH.open("r") as f:
        for unit in json.load(f).get("units", []):
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

    c_file = SRC_ROOT / f"{obj_path}.c"
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
    ref_obj = f"./build/GALE01/obj/{obj_path}.o"
    our_obj = f"./build/GALE01/src/{obj_path}.o"
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

        def get_asm_with_objdump(obj_path: str, func: str, normalize: bool = True) -> str:
            """Extract disassembly for a function using objdump."""
            result = subprocess.run(
                [str(disasm_path), "-d", "-r", obj_path],
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

        def get_asm_with_dtk(obj_path: str, func: str, normalize: bool = True) -> str:
            """Extract disassembly for a function using dtk."""
            with tempfile.TemporaryDirectory() as tmpdir:
                asm_file = Path(tmpdir) / "disasm.s"
                result = subprocess.run(
                    [str(disasm_path), "elf", "disasm", obj_path, str(asm_file)],
                    cwd=ROOT, capture_output=True, text=True
                )
                if result.returncode != 0 or not asm_file.exists():
                    return ""

                asm_content = asm_file.read_text()

            # Parse dtk output format to find the function
            # dtk outputs standard GNU as format: "func_name:" followed by instructions
            lines = asm_content.split("\n")
            in_func = False
            output = []
            instr_offset = 0  # Track offset (each PPC instruction is 4 bytes)

            for line in lines:
                # Function labels in dtk output are like "func_name:" at column 0
                if line.startswith(f"{func}:"):
                    in_func = True
                    instr_offset = 0
                    if normalize:
                        output.append(f"<{func}>:")
                    else:
                        output.append(line)
                elif in_func:
                    # End of function: another label at column 0 or .global/.section directive
                    if line and not line.startswith((" ", "\t")) and (line.endswith(":") or line.startswith(".")):
                        break
                    if normalize and line.strip():
                        # dtk outputs like "  lwz r3, 0(r4)"
                        stripped = line.strip()
                        if stripped and not stripped.startswith("."):  # Skip directives
                            output.append(f"+{instr_offset:03x}: {stripped}")
                            instr_offset += 4  # PPC instructions are 4 bytes
                    elif line.strip():
                        output.append(line)

            return "\n".join(output)

        # Choose the appropriate disassembly function
        if disasm_type == "objdump":
            get_asm = get_asm_with_objdump
        else:
            get_asm = get_asm_with_dtk

        ref_asm = get_asm(str(ROOT / ref_obj), func_name)
        our_asm = get_asm(str(ROOT / our_obj), func_name)

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
            ref_lines = normalize_section_anchor_references(
                ref_lines,
                collect_section_anchor_aliases(ROOT / ref_obj.lstrip("./")),
            )
            our_lines = normalize_section_anchor_references(
                our_lines,
                collect_section_anchor_aliases(ROOT / our_obj.lstrip("./")),
            )
        classification = classify_asm_diff(ref_lines, our_lines)
        add_pad_stack_probe_guidance(
            classification,
            detect_diagnostic_pad_stack_in_source(c_file, func_name),
        )
        matched = is_effective_match(ref_asm, our_asm, classification)
        snapshot_verdict = classification.get("primary") or ""

        fuzzy_pct = get_fuzzy_match_percent(func_name)
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
