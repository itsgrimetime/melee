"""Smoke test for `debug search run` CLI.

Uses --dry-compiler so no real mwcc/wibo/SSH is needed.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.search.cli import _compute_melee_root, _resolve_expected_obj, search_app


def test_compute_melee_root_points_at_repo_root() -> None:
    """Regression guard for the parents[N] off-by-one.

    The computed root must be the melee repo root (contains configure.py and
    src/melee), NOT an ancestor like tools/ — otherwise the non-dry CLI builds
    against tools/build/... and fails for every function.
    """
    root = _compute_melee_root()
    assert root.name == "melee", root
    assert (root / "configure.py").exists(), f"no configure.py under {root}"
    assert (root / "src" / "melee").is_dir(), f"no src/melee under {root}"
    # The buggy parents[3] would land on tools/, which has neither marker.
    assert not (root / "melee-agent").exists(), (
        f"{root} looks like tools/, not the repo root"
    )


def test_search_run_dry(tmp_path: Path) -> None:
    runner = CliRunner()
    seed = tmp_path / "seed.c"
    seed.write_text("int MatToQuat(){return 0;}")
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "MatToQuat",
            "--unit", "quatlib",
            "--no-remote",
            "--seed", str(seed),
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--dry-compiler",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "accounting" in result.stdout.lower()


def test_expected_obj_resolves_original_obj_not_current_build_obj(tmp_path: Path) -> None:
    """The scorer must compare candidates against the target/original object.

    build/GALE01/src/<unit>.o is overwritten by the local candidate compile;
    using it as the expected object makes the baseline score as an exact match.
    """

    report = tmp_path / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/ft/ftdynamics",'
        '"functions":[{"name":"ftCo_8009E7B4"}]}]}'
    )

    resolved = _resolve_expected_obj(
        tmp_path,
        "ftCo_8009E7B4",
        "melee/ft/ftdynamics",
    )

    assert resolved == tmp_path / "build" / "GALE01" / "obj" / "melee" / "ft" / "ftdynamics.o"


def test_expected_obj_fallback_uses_original_obj_tree(tmp_path: Path) -> None:
    resolved = _resolve_expected_obj(
        tmp_path,
        "ftCo_8009E7B4",
        "melee/ft/ftdynamics",
    )

    assert resolved == tmp_path / "build" / "GALE01" / "obj" / "melee" / "ft" / "ftdynamics.o"


def test_search_run_missing_permuter_dir_degrades_to_local_only(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        search_app,
        [
            "run",
            "--function", "ftCo_8009E7B4",
            "--unit", "melee/ft/ftdynamics",
            "--store", str(tmp_path / "store"),
            "--max-iters", "1",
            "--perm-root", str(tmp_path / "missing-decomp-permuter"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "remote producers disabled" in result.stderr
    assert "function dir, compile.sh, settings.toml, target.o" in result.stderr
