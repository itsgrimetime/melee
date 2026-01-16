#!/usr/bin/env python3
"""
Helper script for LLM-driven decompiling. Fixes any missing imports, then
rebuilds and runs objdiff-cli on the specified function.

Usage:
  tools/checkdiff.py <function_name>
  tools/checkdiff.py <function_name> --no-tty  # Force non-interactive mode

Automatically uses non-interactive mode when no TTY is detected (e.g., agents).

Originally from: https://github.com/lukechampine/melee/tree/claude-skills
Adapted for melee-decomp project structure where melee is a symlink.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Support both standalone melee repo and melee-decomp structure
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# Check if we're in melee-decomp (has melee symlink) or standalone melee
if (PROJECT_ROOT / "melee" / "src" / "melee").exists():
    ROOT = PROJECT_ROOT / "melee"
else:
    ROOT = PROJECT_ROOT

REPORT_PATH = ROOT / "build/GALE01/report.json"
SRC_ROOT = ROOT / "src"

# Use our bundled objdiff-cli if available
OBJDIFF_CLI = SCRIPT_DIR / "objdiff-cli"
if not OBJDIFF_CLI.exists():
    OBJDIFF_CLI = "objdiff-cli"  # Fall back to PATH


def find_unit_for_function(func_name: str) -> Optional[str]:
    with REPORT_PATH.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return unit.get("name", "").removeprefix("main/")
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
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return 1

    # diff
    if args.no_tty:
        # Use objdump + diff for non-interactive output (works without TTY)
        objdump = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump"

        import re

        def get_asm(obj_path: str, func: str, normalize: bool = True) -> str:
            """Extract disassembly for a function from object file."""
            result = subprocess.run(
                [objdump, "-d", "-r", obj_path],
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
            diff_data = {
                "function": func_name,
                "reference_lines": len(ref_lines),
                "current_lines": len(our_lines),
                "match": ref_asm == our_asm,
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
