"""Small parser for mwcc-inspect output used by debug inspect diff.

The inspector output is treated as text snapshots, not a semantic IR. The goal
is stable section slicing so diff_report can compare frontend and mid-end
sections before backend pcdump passes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_FUNCTION_RE = re.compile(r"^FUNCTION:\s+(\S+)\s*$")
_SECTION_NAMES = {
    "LOCAL VARIABLES": "Frontend",
    "STATEMENTS": "Frontend",
    "ENODES": "Frontend",
    "OBJOBJECTS": "Frontend",
    "OPTIMIZED IR": "Mid-end",
    "MID-END IR": "Mid-end",
}


@dataclass(frozen=True)
class InspectSnapshot:
    name: str
    text: str


def _slice_function(text: str, function: str) -> list[str]:
    lines = text.splitlines()
    start: int | None = None
    end: int | None = None
    for idx, line in enumerate(lines):
        match = _FUNCTION_RE.match(line.strip())
        if match is None:
            continue
        if match.group(1) == function and start is None:
            start = idx + 1
            continue
        if start is not None:
            end = idx
            break
    if start is None:
        return []
    return lines[start:end]


def parse_inspect_snapshots(text: str, *, function: str) -> list[InspectSnapshot]:
    lines = _slice_function(text, function)
    snapshots: list[InspectSnapshot] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_lines
        if current_name is not None:
            snapshots.append(InspectSnapshot(current_name, "\n".join(current_lines).strip()))
        current_name = None
        current_lines = []

    for raw in lines:
        stripped = raw.strip()
        upper = stripped.upper()
        if upper in _SECTION_NAMES:
            flush()
            current_name = f"{_SECTION_NAMES[upper]}: {upper}"
            current_lines = [stripped]
            continue
        if current_name is not None:
            current_lines.append(raw.rstrip())
    flush()
    return [s for s in snapshots if s.text]
