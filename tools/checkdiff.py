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
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent  # tools/ is in repo root

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
    ap.add_argument("--format", choices=["plain", "color", "json"], default="plain",
                    help="Output format when using --no-tty (default: plain)")
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
    result = subprocess.run(["ninja", our_obj], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print("ninja failed:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
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
            for line in lines:
                if f"<{func}>:" in line:
                    in_func = True
                    if normalize:
                        # Normalize function header to just show the name
                        output.append(f"<{func}>:")
                    else:
                        output.append(line)
                elif in_func:
                    if line and not line.startswith(" ") and ":" in line and "<" in line:
                        break  # start of next function
                    if normalize and line.strip():
                        # Strip the leading address (e.g., "     180:") but keep instruction
                        normalized = re.sub(r"^\s*[0-9a-f]+:\s*", "  ", line)
                        # Also normalize branch target addresses (e.g., "2460 <func+0x34>" -> "<func+0x34>")
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

            for line in lines:
                # Function labels in dtk output are like "func_name:" at column 0
                if line.startswith(f"{func}:"):
                    in_func = True
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
                        # Normalize by stripping leading whitespace to consistent indent
                        stripped = line.strip()
                        if stripped and not stripped.startswith("."):  # Skip directives
                            output.append(f"  {stripped}")
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

        if args.format == "json":
            import json as json_mod
            fuzzy_pct = get_fuzzy_match_percent(func_name)
            diff_data = {
                "function": func_name,
                "reference_lines": len(ref_lines),
                "current_lines": len(our_lines),
                "match": ref_asm == our_asm,
                "fuzzy_match_percent": fuzzy_pct,
                "target_asm": ref_lines,
                "current_asm": our_lines,
                "diff": list(difflib.unified_diff(ref_lines, our_lines,
                    fromfile="expected", tofile="current", lineterm=""))
            }
            print(json_mod.dumps(diff_data, indent=2))
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
