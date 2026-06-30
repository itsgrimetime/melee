"""CLI tests for debug suggest inlines."""
from __future__ import annotations

import json
import pathlib
import subprocess

from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug.source_shape import CandidatePatch, SourceShapeReport


CLI_CWD = pathlib.Path(__file__).parent.parent


def test_suggest_inlines_help() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest", "inlines", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "--function" in proc.stdout
    assert "--source-file" in proc.stdout
    assert "--seed-source" in proc.stdout
    assert "--verify" in proc.stdout
    assert "--apply-best" in proc.stdout
    assert "--trace-copies" in proc.stdout
    assert "--explain" in proc.stdout
    assert "--emit-hunks" in proc.stdout
    assert "--emit-diffs" in proc.stdout


def test_suggest_inlines_rejects_apply_best_without_verify() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "suggest", "inlines",
            "-f", "fn_test",
            "--apply-best",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0
    assert "--apply-best requires --verify" in proc.stderr


def test_suggest_inlines_help_mentions_threshold_and_keep_failed() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "suggest", "inlines", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "--threshold" in proc.stdout
    assert "--keep-failed" in proc.stdout
    assert "--target" in proc.stdout
    assert "--emit-patches" in proc.stdout
    assert "--emit-hunks" in proc.stdout
    assert "--emit-diffs" in proc.stdout
    assert "--checkdiff-timeout" in proc.stdout


def test_suggest_inlines_verify_target_uses_score_source_helper(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    source_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    target_path = melee_root / "target.json"
    target_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        return SourceShapeReport(
            function=kwargs["function"],
            patches=[
                CandidatePatch(
                    candidate_id="local-write-0001",
                    patched_source="void fn_test(void) { Candidate(); }\n",
                    summary="extract block macro",
                    touched_ranges=((1, 2),),
                    metadata={
                        "family": "inline-local-write-helper",
                        "strategy": "block-macro",
                        "source_model_layer_dimension_id": (
                            "inline-local-write-helper"
                        ),
                        "source_hunks": [{"hunk_id": "h001"}],
                    },
                )
            ],
        )

    def fake_score_source(candidates, config):
        captured["candidates"] = candidates
        captured["config"] = config
        assert list(candidates[0].source_hunks) == [{"hunk_id": "h001"}]
        return [
            {
                "candidate_id": candidates[0].candidate_id,
                "family": "inline-local-write-helper",
                "strategy": "block-macro",
                "source_model_layer_dimension_id": "inline-local-write-helper",
                "source_retained": str(config.output_dir / "local-write-0001.c"),
                "pcdump_path": str(config.output_dir / "local-write-0001.pcdump.txt"),
                "source_hunks": [{"hunk_id": "h001"}],
                "target_score": {"matched": 0, "targeted": 1, "virtual_distance": 1},
                "expression_score": {
                    "matched": 0,
                    "targeted": 1,
                    "virtual_distance": 1,
                },
                "structural_guard": {"accepted": True},
                "target_matched": 0,
                "target_targeted": 1,
                "target_virtual_distance": 1,
                "expression_matched": 0,
                "expression_targeted": 1,
                "expression_virtual_distance": 1,
                "score_returncode": 0,
                "terminal_safe": True,
            }
        ]

    import src.mwcc_debug.suggest_inlines as suggest_mod
    import src.mwcc_debug.source_candidate_scoring as scoring_mod

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(suggest_mod, "run", fake_run)
    monkeypatch.setattr(scoring_mod, "score_source_candidates", fake_score_source)

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "suggest",
            "inlines",
            "-f",
            "fn_test",
            "--verify",
            "--target",
            str(target_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.full_unit_source is True
    assert config.checkdiff_guard is True
    assert config.cflags_from == "src/melee/mn/sample.c"
    assert config.target == target_path
    assert (
        str(config.output_dir).startswith(
            str(melee_root / "build" / "diagnostics" / "suggest_inlines")
        )
    )
    payload = json.loads(result.output)
    assert payload["score_mode"] == "score-source"
    assert payload["scores"][0]["status"] == "no_match"
    assert payload["scores"][0]["target_score"]["targeted"] == 1
    assert payload["scores"][0]["status"] != "unscored"


def test_suggest_inlines_source_file_seeds_candidates_and_expression_source(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    source_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "void fn_test(void) { /* LIVE_SOURCE_MARKER */ }\n",
        encoding="utf-8",
    )
    retained_path = tmp_path / "retained.c"
    retained_path.write_text(
        "void fn_test(void) { /* RETAINED_SOURCE_MARKER */ }\n",
        encoding="utf-8",
    )
    retained_pcdump = tmp_path / "retained.pcdump.txt"
    retained_pcdump.write_text("retained pcdump\n", encoding="utf-8")
    target_path = tmp_path / "target.json"
    target_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        source = kwargs["source"]
        captured["run_source"] = source
        return SourceShapeReport(
            function=kwargs["function"],
            patches=[
                CandidatePatch(
                    candidate_id="retained-local-write-0001",
                    patched_source=(
                        source.replace(
                            "RETAINED_SOURCE_MARKER",
                            "RETAINED_SOURCE_MARKER Candidate();",
                        )
                    ),
                    summary="extract block macro",
                    touched_ranges=((1, 1),),
                    metadata={
                        "family": "inline-local-write-helper",
                        "strategy": "block-macro",
                    },
                )
            ],
        )

    def fake_score_source(candidates, config):
        captured["candidates"] = candidates
        captured["config"] = config
        return [
            {
                "candidate_id": candidates[0].candidate_id,
                "family": "inline-local-write-helper",
                "strategy": "block-macro",
                "source_retained": str(
                    config.output_dir / "retained-local-write-0001.c"
                ),
                "pcdump_path": str(
                    config.output_dir / "retained-local-write-0001.pcdump.txt"
                ),
                "target_score": {"matched": 1, "targeted": 1, "virtual_distance": 0},
                "expression_score": {
                    "matched": 1,
                    "targeted": 1,
                    "virtual_distance": 0,
                },
                "target_matched": 1,
                "target_targeted": 1,
                "target_virtual_distance": 0,
                "expression_matched": 1,
                "expression_targeted": 1,
                "expression_virtual_distance": 0,
                "score_returncode": 0,
            }
        ]

    import src.mwcc_debug.suggest_inlines as suggest_mod
    import src.mwcc_debug.source_candidate_scoring as scoring_mod

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(suggest_mod, "run", fake_run)
    monkeypatch.setattr(scoring_mod, "score_source_candidates", fake_score_source)

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "suggest",
            "inlines",
            "-f",
            "fn_test",
            "--source-file",
            str(retained_path),
            "--pcdump",
            str(retained_pcdump),
            "--verify",
            "--target",
            str(target_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "RETAINED_SOURCE_MARKER" in captured["run_source"]
    assert "LIVE_SOURCE_MARKER" not in captured["run_source"]
    candidates = captured["candidates"]
    assert "RETAINED_SOURCE_MARKER Candidate();" in candidates[0].source_text
    assert "LIVE_SOURCE_MARKER" not in candidates[0].source_text
    config = captured["config"]
    assert config.cflags_from == "src/melee/mn/sample.c"
    assert config.expression_source == retained_path.resolve()
    assert config.expression_baseline == retained_pcdump.resolve()


def test_suggest_inlines_score_output_dir_uses_targetless_retained_source(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    source_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("void fn_test(void) { Original(); }\n", encoding="utf-8")
    output_dir = tmp_path / "scores"
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        return SourceShapeReport(
            function=kwargs["function"],
            patches=[
                CandidatePatch(
                    candidate_id="local-write-0001",
                    patched_source="void fn_test(void) { Candidate(); }\n",
                    summary="extract block macro",
                    touched_ranges=((1, 1),),
                    metadata={
                        "family": "inline-local-write-helper",
                        "strategy": "block-macro",
                        "source_model_layer_dimension_id": (
                            "inline-local-write-helper"
                        ),
                        "source_hunks": [{"hunk_id": "h001"}],
                    },
                )
            ],
        )

    def fake_score_source(candidates, config):
        captured["candidates"] = candidates
        captured["config"] = config
        return [
            {
                "candidate_id": candidates[0].candidate_id,
                "family": "inline-local-write-helper",
                "strategy": "block-macro",
                "source_model_layer_dimension_id": "inline-local-write-helper",
                "source_retained": str(config.output_dir / "local-write-0001.c"),
                "pcdump_path": str(config.output_dir / "local-write-0001.pcdump.txt"),
                "source_hunks": [{"hunk_id": "h001"}],
                "match_percent": 95.75,
                "checkdiff_match_percent": 95.75,
                "structural_guard": {
                    "accepted": False,
                    "classification_primary": "instruction-sequence",
                    "normalized_diff_lines": 16,
                },
                "score_returncode": 0,
                "terminal_safe": True,
            }
        ]

    def fake_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["python", "tools/checkdiff.py"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"fuzzy_match_percent": 95.78}),
                stderr="",
            )
        raise AssertionError(f"unexpected subprocess command: {cmd}")

    import src.cli.debug.suggest as suggest_cli
    import src.mwcc_debug.source_candidate_scoring as scoring_mod
    import src.mwcc_debug.suggest_inlines as suggest_mod

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(suggest_mod, "run", fake_run)
    monkeypatch.setattr(scoring_mod, "score_source_candidates", fake_score_source)
    monkeypatch.setattr(suggest_cli.subprocess, "run", fake_subprocess_run)

    result = CliRunner().invoke(
        app,
        [
            "debug",
            "suggest",
            "inlines",
            "-f",
            "fn_test",
            "--verify",
            "--score-output-dir",
            str(output_dir),
            "--emit-hunks",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.target is None
    assert config.output_dir == output_dir
    assert config.full_unit_source is True
    payload = json.loads(result.output)
    assert payload["status"] == "terminal"
    assert payload["score_mode"] == "score-source"
    assert payload["score_output_dir"] == str(output_dir)
    row = payload["score_rows"][0]
    assert row["source_retained"].endswith("local-write-0001.c")
    assert row["pcdump_path"].endswith(".pcdump.txt")
    assert row["source_hunks"] == [{"hunk_id": "h001"}]
    assert row["checkdiff_baseline_pct"] == 95.78
    assert row["checkdiff_delta"] < 0
    proof = payload["source_model_proof"]
    assert proof["status"] == "terminal"
    assert proof["source_family_synthesis"]["retained_scored_probes"][0][
        "source_hunks"
    ]
    assert "source-level rewrite" in proof["next_unsupported_source_model"]


def test_suggest_inlines_rejects_apply_best_with_target_verify() -> None:
    result = CliRunner().invoke(
        app,
        [
            "debug",
            "suggest",
            "inlines",
            "-f",
            "fn_test",
            "--verify",
            "--target",
            "target.json",
            "--apply-best",
        ],
    )

    assert result.exit_code != 0
    assert "--apply-best is not supported with --target" in result.output
