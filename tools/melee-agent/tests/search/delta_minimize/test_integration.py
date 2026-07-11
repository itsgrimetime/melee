from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import src.search.cli as search_cli
from src.search.cli import search_app
from src.search.delta_minimize.run import run_delta_minimize
from tests.search.delta_minimize.test_run import _CountingFixture


FIXTURES = Path(__file__).parents[2] / "fixtures" / "delta_minimize"


def test_wrapper_direct_fixture_has_exact_reproducible_frontier(
    monkeypatch, tmp_path: Path
) -> None:
    fixture = _CountingFixture(tmp_path)
    left = FIXTURES / "left.c"
    right = FIXTURES / "right.c"
    out_dir = tmp_path / "run"
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: FIXTURES)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: left,
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda config: run_delta_minimize(config, backends=fixture.backends()),
    )
    argv = [
        "delta-minimize",
        "--function",
        "f",
        "--left",
        str(left),
        "--right",
        str(right),
        "--out-dir",
        str(out_dir),
        "--json",
    ]

    first = CliRunner().invoke(search_app, argv)
    second = CliRunner().invoke(search_app, argv)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert second.stdout == first.stdout
    result = json.loads(first.stdout)
    assert result["status"] in {"matched", "joint-zero", "frontier"}
    assert result["exact_four_axis"] is True
    assert result["candidate_counts"] == {"complete": 4, "legal": 4, "viable": 4}
    assert result["pareto"]["candidate_ids"]
    assert all(group["minimal_from_left"] for group in result["pareto"]["groups"])
    assert all(group["minimal_from_right"] for group in result["pareto"]["groups"])
    assert fixture.score_calls == 4
    assert (out_dir / "result.json").is_file()
