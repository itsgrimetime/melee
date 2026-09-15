"""Surface-freeze net for the debug CLI carve-out.

Snapshots `--help` for every debug command/group. Any change to the command
surface (names, nesting, options, help text) breaks this test. Regenerate
intentionally with MELEE_REGEN_GOLDEN=1 — never inside a refactor task.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app  # the top-level melee-agent typer app

GOLDEN_DIR = Path(__file__).parent / "golden" / "debug_cli_help"
runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    return _ANSI.sub("", s)


def _canonical_help(s: str) -> str:
    compact = re.sub(r"[\s│╭╮╰╯─]+", "", _strip(s))
    return re.sub(
        r"\[default:/(?:[A-Za-z0-9_.-]+/)+code/decomp(?:-[A-Za-z]*)?(?:…|\])",
        "[default:<HOME>/code/decomp-permuter]",
        compact,
    )


def test_canonical_help_ignores_layout_and_home_expansion() -> None:
    macos = """\
╭─ Options ─╮
│ --perm-root PATH [default:                      │
│                  /Users/mike/code/decomp-permu… │
╰───────────────╯
"""
    linux = """\
╭─ Options ─╮
│ --perm-root PATH [default: /home/runner/code/decomp-permuter] │
╰───────────────╯
"""

    assert _canonical_help(macos) == _canonical_help(linux)


def test_canonical_help_preserves_surface_text() -> None:
    assert _canonical_help("--alpha First option") != _canonical_help(
        "--beta First option"
    )


def _walk_help(argv: list[str]) -> list[tuple[list[str], str]]:
    """Recursively collect every `... --help` path under `debug`.

    Yields ``(argv, stripped_help_stdout)`` so callers can reuse the captured
    help text instead of re-invoking ``--help`` a second time per command.
    """
    # Help goldens are intentionally an 80-column surface. Do not inherit the
    # host terminal width: a one-column difference is enough to reflow long
    # permuter command help without changing the CLI itself.
    out = _strip(
        runner.invoke(
            app,
            argv + ["--help"],
            env={"COLUMNS": "80"},
            terminal_width=80,
        ).stdout
    )
    result = [(argv, out)]
    # Typer renders commands inside a "╭─ Commands ─╮" panel.
    # Each command line looks like: "│ name          description │"
    # Continuation lines look like: "│               more text   │" (name col is spaces)
    # We match only lines where the command name starts right after "│ " with no leading spaces.
    in_cmds = False
    for line in out.splitlines():
        stripped = _strip(line)
        if re.search(r"Commands", stripped) and ("╭" in stripped or "─" in stripped):
            in_cmds = True
            continue
        if in_cmds:
            # Stop at panel close
            if "╰" in stripped:
                in_cmds = False
                continue
            # Command rows: "│ <name>  <description>" — name immediately after "│ "
            # Typer uses at least 2 spaces between name and description.
            m = re.match(r"^[│|]\s([a-z][a-z0-9-]+)\s{2,}", stripped)
            if m:
                result.extend(_walk_help(argv + [m.group(1)]))
    return result


def _slug(argv: list[str]) -> str:
    return "__".join(argv) + ".txt"


def test_debug_help_surface_unchanged() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    regen = os.environ.get("MELEE_REGEN_GOLDEN") == "1"
    failures = []
    walked_help = _walk_help(["debug"])
    walked = {_slug(argv) for argv, _ in walked_help}
    for argv, got in walked_help:
        path = GOLDEN_DIR / _slug(argv)
        if regen:
            path.write_text(got)
            continue
        if not path.exists():
            failures.append(f"missing golden: {path.name} (run MELEE_REGEN_GOLDEN=1)")
        elif _canonical_help(path.read_text()) != _canonical_help(got):
            failures.append(f"help changed for: {' '.join(argv)}")

    # Orphaned-golden detection: a later refactor that drops or renames a command
    # leaves its old golden .txt behind, and the deletion would otherwise go
    # undetected (the comparison loop is driven by the live walker). Catch it.
    stale = {p.name for p in GOLDEN_DIR.glob("*.txt")} - walked
    if regen:
        # Delete orphans so a renamed command can't leave a ghost behind.
        for name in stale:
            (GOLDEN_DIR / name).unlink()
    elif stale:
        failures.append(
            f"stale goldens (run MELEE_REGEN_GOLDEN=1): {', '.join(sorted(stale))}"
        )

    assert not failures, "\n".join(failures)
