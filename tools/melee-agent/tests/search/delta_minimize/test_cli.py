from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

import src.search.cli as search_cli
from src.search.cli import search_app
from src.search.delta_minimize.contracts import AxisDistances, ParetoGroup, ParetoSummary
from src.search.delta_minimize.render import (
    parse_donor_overrides,
    render_delta_minimize_text,
)
from src.search.delta_minimize.run import DeltaMinimizeError, DeltaMinimizeResult

runner = CliRunner()


def _result(*, status: str = "frontier", provisional: bool = False) -> DeltaMinimizeResult:
    axes = AxisDistances(
        opcode=(0, 0),
        color=(1, 2, 3, 4, 5, 6),
        objobjects=(0, 1),
        stack_homes=(2, 8, 1, 0),
    )
    pareto = ParetoSummary(
        status="provisional" if provisional else status,
        candidate_ids=("mask-01", "mask-10"),
        groups=(
            ParetoGroup(
                objective_vector=axes,
                candidate_ids=("mask-01", "mask-10"),
                minimal_from_left=("mask-01",),
                minimal_from_right=("mask-10",),
                representative="mask-01",
            ),
        ),
        best_next="mask-01",
        exact_match_candidate_ids=("mask-10",) if status == "matched" else (),
        joint_solutions=(),
        joint_zero_all_candidate_ids=(),
    )
    return DeltaMinimizeResult(
        schema_version="delta-minimize-result.v1",
        status="provisional" if provisional else status,
        exact_four_axis=not provisional and status != "incomplete",
        function="draw",
        inputs={"left": "/tmp/internal/left.c", "right": "/tmp/internal/right.c"},
        compiler_provenance={"compiler_fingerprint": "mwcc-test"},
        objective_manifest={
            "references": {
                "opcode": {
                    "reference_kind": "absolute",
                    "reference_artifact": "expected.o",
                    "donor": None,
                    "inference_reason": "expected-object",
                    "override": False,
                    "unresolved": [],
                },
                "color": {
                    "reference_kind": "mixed",
                    "reference_artifact": "color-left.pcdump",
                    "donor": "left",
                    "inference_reason": "lower-distance",
                    "override": True,
                    "unresolved": ["role-temp"],
                },
                "objobjects": {
                    "reference_kind": "proxy",
                    "reference_artifact": "left.inspect",
                    "donor": "left",
                    "inference_reason": "inherits-color",
                    "override": False,
                    "unresolved": [],
                },
                "stack-homes": {
                    "reference_kind": "mixed",
                    "reference_artifact": "right.stack.json",
                    "donor": "right",
                    "inference_reason": "lower-distance",
                    "override": False,
                    "unresolved": ["compiler-temp-1"],
                },
            }
        },
        delta_manifest={
            "atoms": [
                {"atom_id": "a", "summary": "helper parameter and call order"},
                {"atom_id": "b", "summary": "wrapper expression"},
            ]
        },
        candidate_budget=64,
        candidate_counts={"legal": 4, "viable": 3, "complete": 3},
        candidates=(
            {
                "candidate_id": "mask-01",
                "applied_atoms": ["a"],
                "source_path": "out/sources/abc.c",
                "distance_from_left": 1,
                "distance_from_right": 1,
                "profile": {"blockers": []},
            },
            {
                "candidate_id": "mask-10",
                "applied_atoms": ["b"],
                "source_path": "out/sources/def.c",
                "distance_from_left": 1,
                "distance_from_right": 1,
                "profile": {"blockers": []},
            },
        ),
        pareto=None if status == "incomplete" else pareto,
        best_next=None if status == "incomplete" else "mask-01",
        cache_stats={"candidate_entries": 4, "parent_entries": 2},
        blockers=("inspector-timeout",) if status == "incomplete" else (),
    )


def _invoke_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    left = tmp_path / "left.c"
    right = tmp_path / "right.c"
    unit = tmp_path / "unit.c"
    left.write_text("int draw(void) { return 1; }\n", encoding="utf-8")
    right.write_text("int draw(void) { return 2; }\n", encoding="utf-8")
    unit.write_text("int draw(void);\n", encoding="utf-8")
    return left, right, unit


def test_parse_donor_overrides_accepts_only_unique_supported_axes() -> None:
    assert parse_donor_overrides(["color=left", "objobjects=right", "stack-homes=left"]) == {
        "color": "left",
        "objobjects": "right",
        "stack-homes": "left",
    }


def test_parse_donor_overrides_rejects_invalid_and_duplicate_values() -> None:
    for values in (
        ["opcode=left"],
        ["color=middle"],
        ["color =left"],
        ["color= left"],
        ["color=left=right"],
        ["color=left", "color=right"],
        [""],
    ):
        try:
            parse_donor_overrides(values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid donors: {values!r}")


def test_delta_minimize_cli_passes_all_options(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    target = tmp_path / "target.yaml"
    target.write_text("target\n", encoding="utf-8")
    captured = {}

    def fake_run(config):
        captured["config"] = config
        return _result()

    monkeypatch.setattr(search_cli, "run_delta_minimize", fake_run)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )

    result = runner.invoke(
        search_app,
        [
            "delta-minimize",
            "--function",
            "draw",
            "--left",
            str(left),
            "--right",
            str(right),
            "--out-dir",
            "results",
            "--max-candidates",
            "17",
            "--target",
            str(target),
            "--donor",
            "color=left",
            "--no-objobjects",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "frontier"
    config = captured["config"]
    assert config.left == left.resolve()
    assert config.right == right.resolve()
    assert config.cflags_from == unit
    assert config.out_dir == (tmp_path / "results").resolve()
    assert config.max_candidates == 17
    assert config.target_path == target.resolve()
    assert dict(config.donor_overrides) == {"color": "left"}
    assert config.include_objobjects is False


def test_delta_minimize_cli_defaults_are_locked(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    captured = {}
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda config: (captured.__setitem__("config", config), _result())[1],
    )

    result = runner.invoke(
        search_app,
        ["delta-minimize", "-f", "draw", "--left", str(left), "--right", str(right)],
    )

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.out_dir == (tmp_path / "build/delta-minimize").resolve()
    assert config.max_candidates == 64
    assert config.include_objobjects is True


def test_delta_minimize_cli_rejects_invalid_donors_missing_paths_and_budget(tmp_path: Path) -> None:
    left, right, _unit = _invoke_paths(tmp_path)
    cases = (
        ["--left", str(left), "--right", str(right), "--donor", "opcode=left"],
        ["--left", str(tmp_path / "missing.c"), "--right", str(right)],
        ["--left", str(left), "--right", str(right), "--max-candidates", "0"],
    )
    for tail in cases:
        result = runner.invoke(search_app, ["delta-minimize", "-f", "draw", *tail])
        assert result.exit_code == 2, result.output


def test_delta_minimize_cli_rejects_symlink_target(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    real = tmp_path / "real-target.yaml"
    real.write_text("target\n", encoding="utf-8")
    target = tmp_path / "target.yaml"
    target.symlink_to(real)
    linked_parent = tmp_path / "linked-target-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    broken = tmp_path / "broken-target.yaml"
    broken.symlink_to(tmp_path / "missing-target.yaml")
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )

    for unsafe_target in (target, linked_parent / real.name, broken):
        result = runner.invoke(
            search_app,
            [
                "delta-minimize",
                "-f",
                "draw",
                "--left",
                str(left),
                "--right",
                str(right),
                "--target",
                str(unsafe_target),
            ],
        )

        assert result.exit_code == 2
        assert "target" in result.output.lower()


def test_delta_minimize_cli_rejects_symlinked_source_roots(tmp_path: Path) -> None:
    left, right, _unit = _invoke_paths(tmp_path)
    linked_left = tmp_path / "linked-left.c"
    linked_left.symlink_to(left)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    broken_source = tmp_path / "broken-left.c"
    broken_source.symlink_to(tmp_path / "missing-left.c")

    for source in (linked_left, linked_parent / right.name, broken_source):
        result = runner.invoke(
            search_app,
            [
                "delta-minimize",
                "-f",
                "draw",
                "--left",
                str(source),
                "--right",
                str(right),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "unsafe" in result.output.lower()


def test_delta_minimize_cli_rejects_symlinked_output_components(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    linked_output = tmp_path / "linked-output"
    linked_output.symlink_to(real_output, target_is_directory=True)
    broken_output = tmp_path / "broken-output"
    broken_output.symlink_to(tmp_path / "missing-output", target_is_directory=True)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )

    for output in (linked_output, linked_output / "nested", broken_output):
        result = runner.invoke(
            search_app,
            [
                "delta-minimize",
                "-f",
                "draw",
                "--left",
                str(left),
                "--right",
                str(right),
                "--out-dir",
                str(output),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "unsafe" in result.output.lower()


def test_delta_minimize_cli_rejects_file_output_components(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    output_file = tmp_path / "output-file"
    output_file.write_text("not a directory\n", encoding="utf-8")
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )

    for output in (output_file, output_file / "nested"):
        result = runner.invoke(
            search_app,
            [
                "delta-minimize",
                "-f",
                "draw",
                "--left",
                str(left),
                "--right",
                str(right),
                "--out-dir",
                str(output),
            ],
        )
        assert result.exit_code == 2, result.output
        assert "not a directory" in result.output.lower()


def test_delta_minimize_cli_accepts_safe_relative_paths(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    captured = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda config: (captured.__setitem__("config", config), _result())[1],
    )

    result = runner.invoke(
        search_app,
        [
            "delta-minimize",
            "-f",
            "draw",
            "--left",
            left.name,
            "--right",
            right.name,
            "--out-dir",
            "results",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["config"].left == left
    assert captured["config"].right == right
    assert captured["config"].out_dir == tmp_path / "results"


def test_delta_minimize_cli_falls_back_to_cross_worktree_unit_path(
    monkeypatch, tmp_path: Path
) -> None:
    left, _right, _unit = _invoke_paths(tmp_path)
    repo_unit = tmp_path / "src" / "melee" / "mn" / "mndiagram.c"
    repo_unit.parent.mkdir(parents=True)
    repo_unit.write_text("int f(void);\n", encoding="utf-8")
    other_root = tmp_path / "other-worktree"
    external_right = other_root / "src" / "melee" / "mn" / "mndiagram.c"
    external_right.parent.mkdir(parents=True)
    external_right.write_text("int f(void) { return 2; }\n", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            search_cli.typer.BadParameter("function absent from report")
        ),
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda config: (captured.__setitem__("config", config), _result())[1],
    )

    result = runner.invoke(
        search_app,
        [
            "delta-minimize",
            "-f",
            "f",
            "--left",
            str(left),
            "--right",
            str(external_right),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["config"].cflags_from == repo_unit.resolve()


def test_delta_minimize_cli_reports_domain_errors_as_usage(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda _config: (_ for _ in ()).throw(
            DeltaMinimizeError("candidate-budget-exceeded", {"required": 65, "budget": 64})
        ),
    )

    result = runner.invoke(
        search_app,
        ["delta-minimize", "-f", "draw", "--left", str(left), "--right", str(right)],
    )

    assert result.exit_code == 2
    assert "candidate-budget-exceeded" in result.output
    assert "budget=64" in result.output
    assert "required=65" in result.output
    assert "increase" in result.output
    assert "max-candidates" in result.output


def test_delta_minimize_cli_reports_actionable_objective_ambiguity(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )
    cases = (
        ("ambiguous-color-target", ("--target", "PATH")),
        ("ambiguous-color-donor", ("--donor", "color=left|right")),
        ("ambiguous-objobject-donor", ("--donor", "objobjects", "left|right")),
        ("ambiguous-stack-home-donor", ("--donor", "stack-homes", "left|right")),
    )
    for reason, hints in cases:
        monkeypatch.setattr(
            search_cli,
            "run_delta_minimize",
            lambda _config, reason=reason: (_ for _ in ()).throw(DeltaMinimizeError(reason)),
        )
        result = runner.invoke(
            search_app,
            ["delta-minimize", "-f", "draw", "--left", str(left), "--right", str(right)],
        )
        assert result.exit_code == 2
        assert reason in result.output
        for hint in hints:
            assert hint in result.output
        assert result.stdout == ""


def test_delta_minimize_incomplete_renders_then_exits_four(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )
    monkeypatch.setattr(search_cli, "run_delta_minimize", lambda _config: _result(status="incomplete"))

    result = runner.invoke(
        search_app,
        ["delta-minimize", "-f", "draw", "--left", str(left), "--right", str(right)],
    )

    assert result.exit_code == 4
    assert "status: incomplete" in result.stdout
    assert "inspector-timeout" in result.stdout


def test_delta_minimize_json_is_pure_and_deterministic(monkeypatch, tmp_path: Path) -> None:
    left, right, unit = _invoke_paths(tmp_path)
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: tmp_path)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: unit,
    )
    monkeypatch.setattr(search_cli, "run_delta_minimize", lambda _config: _result())
    argv = [
        "delta-minimize",
        "-f",
        "draw",
        "--left",
        str(left),
        "--right",
        str(right),
        "--json",
    ]

    first = runner.invoke(search_app, argv)
    second = runner.invoke(search_app, argv)

    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["schema_version"] == "delta-minimize-result.v1"
    assert not first.stdout.startswith("Running")


def test_text_renderer_shows_complete_frontier_and_provenance() -> None:
    text = render_delta_minimize_text(_result())

    assert "status: frontier (exact four-axis)" in text
    assert "candidates: legal=4 viable=3 complete=3 budget=64" in text
    assert "color: mixed donor=left override=yes" in text
    assert "objobjects: proxy donor=left" in text
    assert "unresolved=role-temp" in text
    assert "helper parameter and call order" in text
    assert "frontier group 1" in text
    assert "opcode=(0, 0)" in text
    assert "candidates=mask-01, mask-10" in text
    assert "minimal-from-left=mask-01" in text
    assert "minimal-from-right=mask-10" in text
    assert "representative=mask-01" in text
    assert "best next: mask-01" in text
    assert "apply a: helper parameter and call order" in text
    assert "revert a: helper parameter and call order" in text
    assert "tied candidate mask-10" in text


def test_text_renderer_summarizes_joint_zero_edits() -> None:
    result = _result()
    assert result.pareto is not None
    result = replace(
        result,
        pareto=replace(
            result.pareto,
            joint_solutions=("mask-01",),
            joint_zero_all_candidate_ids=("mask-01", "mask-10"),
        ),
    )

    text = render_delta_minimize_text(result)

    assert "joint-zero minimized candidate mask-01" in text
    assert "joint-zero tied candidate mask-10" in text
    assert "apply b: wrapper expression" in text


def test_text_renderer_marks_provisional_and_proxy_zero_meaning() -> None:
    text = render_delta_minimize_text(_result(provisional=True))

    assert "PROVISIONAL three-axis; ObjObject scoring disabled" in text
    assert "ObjObject zero means matches the inferred donor" in text


def test_text_renderer_lists_all_blockers() -> None:
    result = replace(
        _result(status="incomplete"),
        inputs={
            "left": "/tmp/internal/left.c",
            "right": "/tmp/internal/right.c",
            "out_dir": "/tmp/internal/resume",
        },
        blockers=("inspector-timeout", "ambiguous-color-donor"),
    )

    text = render_delta_minimize_text(result)

    assert "blockers:" in text
    assert "- inspector-timeout" in text
    assert "- ambiguous-color-donor" in text
    assert "next action: restore inspector infrastructure, then resume this run" in text
    assert "required override: --donor color=left|right" in text
    assert (
        "melee-agent debug search delta-minimize --function draw "
        "--left /tmp/internal/left.c --right /tmp/internal/right.c "
        "--out-dir /tmp/internal/resume"
    ) in text


def test_text_renderer_shell_quotes_only_recorded_resume_values() -> None:
    result = replace(
        _result(status="incomplete"),
        inputs={
            "left": "/tmp/left source.c",
            "right": "/tmp/right;touch injected.c",
            "out_dir": "/tmp/resume output",
            "target_path": "/tmp/existing target.yaml",
            "donor_overrides": {"color": "right"},
            "include_objobjects": False,
        },
        blockers=("candidate-score-infrastructure",),
    )

    text = render_delta_minimize_text(result)

    assert "--left '/tmp/left source.c'" in text
    assert "--right '/tmp/right;touch injected.c'" in text
    assert "--out-dir '/tmp/resume output'" in text
    assert "--max-candidates 64" in text
    assert "--target '/tmp/existing target.yaml'" in text
    assert "--donor color=right --no-objobjects" in text
