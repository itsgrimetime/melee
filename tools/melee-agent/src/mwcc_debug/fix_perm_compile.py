"""Fix decomp-permuter's generated `compile.sh` for macOS+wine.

Background: `import.py` writes a `compile.sh` that converts `$1` to an
absolute mac path via `realpath`, then passes that to `wine
mwcceppc.exe`. mwcc on wine triggers an assertion
(`MacSpecs.c:264: *pb == OS_PATHSEP`) when given Unix-absolute paths.
The same flags with a relative path work fine.

Fix: stage the candidate source as a relative path inside the project
tree (which is `nonmatchings/.permuter_stage_<pid>.c`, git-ignored)
and pass THAT to mwcc. The PID-based name is parallel-safe across
permuter's worker threads.

This rewrite is idempotent — calling on an already-fixed script is a
no-op and reports as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Detection pattern: the buggy line `INPUT="$(realpath "$1")"` is the
# unambiguous signature of import.py's generated compile.sh.
_BUGGY_INPUT_LINE_RE = re.compile(r'^INPUT="\$\(realpath\s+"\$1"\)"\s*$')

# Marker line indicating we've already rewritten this file.
_FIX_MARKER = "# Patched by melee-agent debug fix-perm-compile"


@dataclass
class FixResult:
    path: Path
    action: str  # "fixed" | "already-fixed" | "not-applicable" | "skipped"
    reason: str = ""


def _read_lines(p: Path) -> list[str]:
    return p.read_text().splitlines()


def _is_already_fixed(lines: list[str]) -> bool:
    return any(_FIX_MARKER in line for line in lines)


def _has_buggy_pattern(lines: list[str]) -> bool:
    return any(_BUGGY_INPUT_LINE_RE.match(line) for line in lines)


def _build_fixed_lines(
    original_lines: list[str],
    project_root: Path,
) -> list[str]:
    """Rewrite the compile.sh lines to use the staging trick.

    The original script has the shape:
        #!/usr/bin/env bash
        INPUT="$(realpath "$1")"
        OUTPUT="$(realpath "$3")"
        cd <project_root>
        wine ... "$INPUT" -o "$OUTPUT"

    We rewrite to:
        #!/usr/bin/env bash
        # Patched by melee-agent debug fix-perm-compile
        set -e
        INPUT_ABS="$(realpath "$1")"
        OUTPUT_ABS="$(realpath "$3")"
        cd <project_root>
        STAGE="nonmatchings/.permuter_stage_$$.c"
        cp "$INPUT_ABS" "$STAGE"
        trap 'rm -f "$STAGE"' EXIT
        INPUT="$STAGE"
        OUTPUT="$OUTPUT_ABS"
        wine ... "$INPUT" -o "$OUTPUT"

    Net effect: the absolute path of the .o output is preserved (mwcc
    can write to Z:/var/folders/... — output path doesn't hit the
    OS_PATHSEP assertion), but the .c input is staged relative.
    """
    out: list[str] = []
    seen_shebang = False
    skip_input_output_lines = False

    for line in original_lines:
        if not seen_shebang and line.startswith("#!"):
            out.append(line)
            out.append(_FIX_MARKER)
            out.append("set -e")
            seen_shebang = True
            continue

        # Replace the original INPUT/OUTPUT lines
        if _BUGGY_INPUT_LINE_RE.match(line):
            out.append('INPUT_ABS="$(realpath "$1")"')
            continue
        if line.strip() == 'OUTPUT="$(realpath "$3")"':
            out.append('OUTPUT_ABS="$(realpath "$3")"')
            continue

        # After `cd <project_root>`, inject staging block
        if line.startswith("cd ") and not skip_input_output_lines:
            out.append(line)
            out.append('STAGE="nonmatchings/.permuter_stage_$$.c"')
            out.append('mkdir -p nonmatchings')
            out.append('cp "$INPUT_ABS" "$STAGE"')
            out.append("trap 'rm -f \"$STAGE\"' EXIT")
            out.append('INPUT="$STAGE"')
            out.append('OUTPUT="$OUTPUT_ABS"')
            skip_input_output_lines = True
            continue

        out.append(line)

    return out


def fix_compile_sh(
    compile_sh_path: Path,
    project_root: Optional[Path] = None,
) -> FixResult:
    """Rewrite a single compile.sh to use the staging trick.

    Idempotent: if the file is already patched, returns action='already-fixed'.
    If the file doesn't match the expected import.py-generated shape,
    returns action='not-applicable' (caller can choose to error or skip).

    `project_root` is only used for the FixResult's debug info — the
    project root is determined from the `cd ...` line in the original
    script, so we don't need it for the rewrite itself.
    """
    if not compile_sh_path.exists():
        return FixResult(
            path=compile_sh_path,
            action="skipped",
            reason="file does not exist",
        )

    lines = _read_lines(compile_sh_path)

    if _is_already_fixed(lines):
        return FixResult(
            path=compile_sh_path,
            action="already-fixed",
            reason="found fix marker",
        )

    if not _has_buggy_pattern(lines):
        return FixResult(
            path=compile_sh_path,
            action="not-applicable",
            reason="no INPUT=\"$(realpath \"$1\")\" line found",
        )

    new_lines = _build_fixed_lines(lines, project_root or Path("."))
    compile_sh_path.write_text("\n".join(new_lines) + "\n")
    # Preserve executable bit
    compile_sh_path.chmod(0o755)

    return FixResult(
        path=compile_sh_path,
        action="fixed",
        reason="rewrote INPUT/OUTPUT to use nonmatchings/.permuter_stage_$$.c",
    )


def fix_perm_dir(
    perm_dir: Path,
    project_root: Optional[Path] = None,
) -> FixResult:
    """Find the compile.sh inside a `nonmatchings/<fn>/` dir and fix it.

    Returns action='skipped' if no compile.sh is present.
    """
    compile_sh = perm_dir / "compile.sh"
    if not compile_sh.exists():
        return FixResult(
            path=compile_sh,
            action="skipped",
            reason=f"no compile.sh in {perm_dir}",
        )
    return fix_compile_sh(compile_sh, project_root=project_root)
