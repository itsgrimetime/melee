"""Part C — §6.4 no-leak / restore tests.

Two tests:
1. test_dry_run_leaves_repo_clean       — a dry search leaves the repo tree untouched
2. test_stage_for_verify_restores_on_exception — ArtifactStore.stage_for_verify
   restores the build object even when an exception escapes the with-block.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.search.store import ArtifactStore


# ---------------------------------------------------------------------------
# Test 1: dry run leaves the repo tree clean
# ---------------------------------------------------------------------------

def test_dry_run_leaves_repo_clean(tmp_path: Path) -> None:
    """Running the substrate's dry code path must not leave any mutations in
    the melee repo working tree.

    We drive the same code path as ``debug search run --dry-compiler
    --no-remote`` directly (via the CLI runner) so we don't need mwcc/wibo.
    After the run, we assert ``git status --porcelain`` reports no changes in
    the melee repo root.
    """
    from typer.testing import CliRunner
    from src.search.cli import search_app, _compute_melee_root

    melee_root = _compute_melee_root()

    # Snapshot the working-tree state BEFORE the run
    before = _git_status(melee_root)

    seed = tmp_path / "seed.c"
    seed.write_text("int MatToQuat(){return 0;}")

    runner = CliRunner()
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "sysdolphin/baselib/quatlib",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "search-store"),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )
    assert result.exit_code == 0, (
        f"CLI exited {result.exit_code}:\n{result.output}"
    )

    # Snapshot AFTER the run — must match the before snapshot
    after = _git_status(melee_root)
    assert after == before, (
        "dry search left the repo tree dirty!\n"
        f"before: {before!r}\n"
        f"after:  {after!r}"
    )


def _git_status(repo_root: Path) -> str:
    """Return the ``git status --porcelain`` output for *repo_root*."""
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Test 2: stage_for_verify restores build object on exception
# ---------------------------------------------------------------------------

def test_stage_for_verify_restores_on_exception(tmp_path: Path) -> None:
    """ArtifactStore.stage_for_verify must restore the build object to its
    original bytes even when an exception is raised inside the with-block.
    """
    store = ArtifactStore(root=tmp_path / "store")

    original_bytes = b"ORIGINAL_BUILD_OBJECT"
    candidate_bytes = b"CANDIDATE_OBJECT"

    build_obj = tmp_path / "build.o"
    build_obj.write_bytes(original_bytes)

    cand_obj = tmp_path / "candidate.o"
    cand_obj.write_bytes(candidate_bytes)

    # Verify the context manager swaps the file in...
    class _SentinelError(RuntimeError):
        pass

    with pytest.raises(_SentinelError):
        with store.stage_for_verify(build_obj, cand_obj):
            # Inside the block: build_obj should contain the candidate bytes
            assert build_obj.read_bytes() == candidate_bytes, (
                "stage_for_verify did not copy candidate into build_obj"
            )
            raise _SentinelError("injected exception to test restore")

    # After the exception: build_obj must be restored to original bytes
    assert build_obj.exists(), "build_obj was deleted instead of restored"
    assert build_obj.read_bytes() == original_bytes, (
        f"build_obj was NOT restored after exception; "
        f"got {build_obj.read_bytes()!r}, expected {original_bytes!r}"
    )
