from __future__ import annotations

import pathlib
import tomllib

import src.cli


def test_coverage_data_file_avoids_package_root_stale_coverage() -> None:
    pyproject = pathlib.Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())

    coverage_run = config["tool"]["coverage"]["run"]
    assert coverage_run["data_file"] == ".pytest_cache/.coverage"
    assert src.cli.__name__ == "src.cli"
