"""CLI tests for `melee-agent debug inspect diff`."""
from __future__ import annotations

import subprocess
from pathlib import Path


MELEE_AGENT = Path(__file__).parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", "-m", "src.cli", "debug", "inspect", "diff", *args],
        cwd=MELEE_AGENT,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_diff_help_mentions_source_and_pcdump_modes() -> None:
    proc = run_cli("--help")

    assert proc.returncode == 0
    assert "source or pcdump" in proc.stdout
    assert "--fn" in proc.stdout
    assert "--timeout" in proc.stdout
    assert "--inspect-a" in proc.stdout
    assert "--inspect-b" in proc.stdout


def test_diff_requires_function() -> None:
    proc = run_cli("a.c", "b.c")

    assert proc.returncode != 0
    assert "--fn/--function is required" in proc.stderr


def test_diff_accepts_existing_pcdump_files(tmp_path: Path) -> None:
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text(
        "Starting function fn_test\n"
        "BEFORE REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r32, 0\n"
        "AFTER REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r3, 0\n",
        encoding="utf-8",
    )
    right.write_text(left.read_text(encoding="utf-8"), encoding="utf-8")

    proc = run_cli(str(left), str(right), "--fn", "fn_test")

    assert proc.returncode == 0
    assert "NO DIVERGENCE" in proc.stdout


def test_diff_source_mode_can_be_exercised_with_fixture_pcdumps(tmp_path: Path) -> None:
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text(
        "Starting function fn_test\n"
        "BEFORE REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r32, 0\n"
        "AFTER REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r3, 0\n",
        encoding="utf-8",
    )
    right.write_text(
        "Starting function fn_test\n"
        "BEFORE REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r32, 1\n"
        "AFTER REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r3, 1\n",
        encoding="utf-8",
    )

    proc = run_cli(str(left), str(right), "--function", "fn_test")

    assert proc.returncode == 0
    assert "EARLIEST DIVERGENCE: BEFORE REGISTER COLORING" in proc.stdout


def test_diff_accepts_explicit_inspect_snapshots_for_staged_lowering(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "same.txt"
    pcdump.write_text(
        "Starting function fn_test\n"
        "BEFORE REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r32, 0\n"
        "AFTER REGISTER COLORING\n"
        "fn_test\n"
        "B0: Succ={} Pred={} Labels={L0 }\n"
        "    li r3, 0\n",
        encoding="utf-8",
    )
    inspect_a = tmp_path / "baseline.inspect.txt"
    inspect_b = tmp_path / "candidate.inspect.txt"
    inspect_a.write_text(
        "FUNCTION: fn_test\n"
        "STATEMENTS\n"
        "  b34 = helper(entity)\n"
        "ENODES\n"
        "  compare b34 == 1\n",
        encoding="utf-8",
    )
    inspect_b.write_text(
        "FUNCTION: fn_test\n"
        "STATEMENTS\n"
        "  b34 = helper(entity)\n"
        "  if (b34 == 0) goto zero\n"
        "ENODES\n"
        "  compare b34 == 0\n",
        encoding="utf-8",
    )

    proc = run_cli(
        str(pcdump),
        str(pcdump),
        "--function",
        "fn_test",
        "--inspect-a",
        str(inspect_a),
        "--inspect-b",
        str(inspect_b),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "EARLIEST DIVERGENCE: Frontend: STATEMENTS" in proc.stdout
    assert "LOWERING SUMMARY" in proc.stdout
    assert "earliest stage: front-end source IR" in proc.stdout


def test_dump_local_subcommand_is_callable() -> None:
    """`debug inspect diff` subprocess-invokes `python -m src.cli debug dump local`
    to compile .c inputs to pcdumps. If that subcommand is ever renamed or
    removed, every source-mode diff invocation breaks at runtime with no unit
    test catching it (the unit tests mock subprocess.run). This integration
    smoke-test invokes the real CLI to confirm the command path resolves; it
    pairs with the cmd[:6] assertion in test_mwcc_debug_diff_capture.py.
    """
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "dump", "local", "--help"],
        cwd=MELEE_AGENT,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, f"`debug dump local --help` failed: {proc.stderr}"
    # Sanity-check the flags diff_capture.py depends on still exist.
    assert "--output" in proc.stdout
    assert "--no-cache-sync" in proc.stdout
    assert "--function" in proc.stdout
