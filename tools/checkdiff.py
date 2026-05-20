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

# Tool paths
TOOLS_CACHE_DIR = Path.home() / ".cache" / "melee-tools"
DTK_VERSION = "v1.8.0"

# Use our bundled objdiff-cli if available
OBJDIFF_CLI = SCRIPT_DIR / "objdiff-cli"
if not OBJDIFF_CLI.exists():
    OBJDIFF_CLI = "objdiff-cli"  # Fall back to PATH


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
            return f"https://github.com/encounter/decomp-toolkit/releases/download/{DTK_VERSION}/dtk-macos-arm64"
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


def acquire_checkdiff_lock(obj_path: str):
    """Acquire a per-object lock for compile-producing checkdiff work."""
    if os.environ.get("CHECKDIFF_NO_LOCK"):
        return None

    try:
        import fcntl
    except ImportError:
        return None

    lock_dir = Path(tempfile.gettempdir()) / "melee-checkdiff-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str((ROOT / obj_path).resolve()).encode()).hexdigest()[:12]
    lock_path = lock_dir / f"{Path(obj_path).name}.{digest}.lock"
    lock_file = lock_path.open("w")

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"waiting for checkdiff lock: {Path(obj_path).name}", file=sys.stderr)
        start = time.monotonic()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elapsed = time.monotonic() - start
        print(f"acquired checkdiff lock after {elapsed:.1f}s", file=sys.stderr)

    return lock_file


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

    if len(ref_lines) != len(our_lines):
        reasons.append(f"line count differs: expected {len(ref_lines)}, current {len(our_lines)}")

    if ref_mnemonics == our_mnemonics:
        reasons.append("opcode sequence matches; differences are operands, registers, labels, or offsets")
        primary = "operand-register-or-offset"
    else:
        primary = "instruction-sequence"

    if ref_calls != our_calls:
        reasons.append("call shape differs; check prototypes, return types, and inline boundaries")
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
        primary = "stack-layout" if primary != "instruction-sequence" else primary
    if data_symbol_diffs:
        reasons.append(f"{data_symbol_diffs} differing paired lines reference data/symbol relocations")
        if primary == "operand-register-or-offset":
            primary = "data-symbol-or-relocation"
    if likely_register_diffs:
        reasons.append(f"{likely_register_diffs} differing paired lines look register-only after normalization")
        if primary == "operand-register-or-offset":
            primary = "register-allocation"

    if not reasons:
        reasons.append("differences require direct inspection")

    return {"primary": primary, "reasons": reasons}


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


def get_fuzzy_match_percent(func_name: str) -> Optional[float]:
    """Get the fuzzy_match_percent for a function from report.json."""
    with REPORT_PATH.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return function.get("fuzzy_match_percent")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("function", help="Function name")
    ap.add_argument("--no-tty", action="store_true",
                    help="Force non-interactive output (auto-detected if no TTY)")
    ap.add_argument("--format", choices=["plain", "side-by-side", "json"], default="side-by-side",
                    help="Output format when using --no-tty (default: side-by-side)")
    ap.add_argument("--no-build", action="store_true",
                    help="Skip the ninja rebuild step and diff the .o as-is. "
                         "Use this when the .o has been post-processed externally "
                         "(e.g. by `melee-agent debug name-magic`).")
    args = ap.parse_args()

    # Auto-detect TTY - use non-interactive mode if no TTY available
    if not sys.stdout.isatty():
        args.no_tty = True

    func_name = args.function

    # locate object file by parsing report.json
    obj_path = find_unit_for_function(func_name)
    if obj_path is None:
        print(f"error: could not find function '{func_name}' in report.json", file=sys.stderr)
        return 1

    c_file = SRC_ROOT / f"{obj_path}.c"
    lock_handle = acquire_checkdiff_lock(obj_path)
    _ = lock_handle  # Keep the lock file alive until process exit.

    # fix includes (optional - lukechampine's repo has this)
    fix_includes = ROOT / "tools" / "fix_includes.py"
    if fix_includes.exists():
        result = subprocess.run(
            [sys.executable, str(fix_includes), str(c_file)],
            cwd=ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"fix_includes.py failed:", file=sys.stderr)
            print(result.stderr.decode(), file=sys.stderr)
            return 1

    # build
    ref_obj = f"./build/GALE01/obj/{obj_path}.o"
    our_obj = f"./build/GALE01/src/{obj_path}.o"
    if not args.no_build:
        result = subprocess.run(["ninja", our_obj], cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            print("ninja failed:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

        # Regenerate report.json to get fresh fuzzy_match_percent
        # This is needed because the VS Code extension relies on accurate match percentages
        result = subprocess.run(
            ["ninja", "build/GALE01/report.json"],
            cwd=ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            print("warning: failed to regenerate report.json", file=sys.stderr)
    else:
        # --no-build: caller has post-processed the .o; just verify it exists.
        if not (ROOT / our_obj.lstrip("./")).exists():
            print(f"error: --no-build given but {our_obj} not found; "
                  f"build it first (or omit --no-build)", file=sys.stderr)
            return 1

    # diff
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
        classification = classify_asm_diff(ref_lines, our_lines)

        fuzzy_pct = get_fuzzy_match_percent(func_name)
        metrics = compute_structural_metrics(ref_lines, our_lines)
        prev_metrics = load_history(func_name)
        progress_note = make_progress_note(fuzzy_pct, metrics, prev_metrics)
        snapshot = {
            "fuzzy_match_percent": fuzzy_pct,
            **metrics,
            "matched": ref_asm == our_asm,
        }
        save_history(func_name, snapshot)

        if args.format == "json":
            import json as json_mod
            diff_data = {
                "function": func_name,
                "reference_lines": len(ref_lines),
                "current_lines": len(our_lines),
                "match": ref_asm == our_asm,
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
        elif args.format == "side-by-side":
            # Side-by-side diff (better for agents to understand)
            if ref_asm == our_asm:
                print(f"--- MATCH: {func_name} matches! ---")
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
                print(f"\n--- MISMATCH: {func_name} does not match ---")
                result = subprocess.CompletedProcess([], 1)
            else:
                print(f"--- MATCH: {func_name} matches! ---")
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

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
