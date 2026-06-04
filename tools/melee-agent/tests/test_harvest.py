from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

import src.harvest as harvest_module
from typer.testing import CliRunner

from src.harvest import (
    HarvestRequest,
    HarnessProcessResult,
    best_validated_candidate,
    extract_candidate_score,
    load_queue_rows,
    load_target_map,
    resolve_source_file,
    run_harvest,
    select_harness,
    summarize_ledger,
    write_ledger,
)


cli_runner = CliRunner()

HEADER = [
    "match_percent",
    "function",
    "primary",
    "subcategory",
    "frame_cause",
    "frame_verdict",
    "frame_closability_tier",
    "frame_attribution_status",
    "frame_source_object_symbol",
    "source_actionability",
    "headline_tool",
    "actionability_reason",
    "decl_order_best_delta",
    "decl_order_best_ordering",
    "decl_order_evaluated_status",
    "decl_order_candidate_count",
    "file_path",
    "frame_next_command",
    "next_command",
]


def _write_queue(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(HEADER)]
    for row in rows:
        lines.append("\t".join(row.get(field, "") for field in HEADER))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(
    function: str,
    *,
    match_percent: str = "99.0",
    file_path: str = "melee/demo.c",
    headline_tool: str = "frame-transform-search",
    source_actionability: str = "source-reachable-candidate",
    frame_closability_tier: str = "current-tools-padstack",
    frame_next_command: str = "",
    next_command: str = "",
) -> dict[str, str]:
    return {
        "match_percent": match_percent,
        "function": function,
        "primary": "stack-layout",
        "subcategory": "frame",
        "frame_closability_tier": frame_closability_tier,
        "source_actionability": source_actionability,
        "headline_tool": headline_tool,
        "file_path": file_path,
        "frame_next_command": frame_next_command,
        "next_command": next_command,
    }


def _name_magic_row(function: str, *, primary: str) -> dict[str, str]:
    row = _row(
        function,
        headline_tool="checkdiff-name-magic",
        source_actionability="current-tools-data-symbol",
        frame_closability_tier="",
    )
    row["primary"] = primary
    row["subcategory"] = "persistent-data-symbol-or-relocation"
    return row


def _repo_with_source(tmp_path: Path, rel_path: str = "melee/demo.c") -> Path:
    repo_root = tmp_path / "repo"
    source_path = repo_root / "src" / rel_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("void demo_fn(void) {}\n", encoding="utf-8")
    return repo_root


def _json_runner(payload: dict) -> tuple[list[list[str]], object]:
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        return HarnessProcessResult(
            command=args,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    return calls, runner


def _match_process(
    function: str,
    *,
    match: bool,
    percent: float,
    primary: str,
) -> HarnessProcessResult:
    return HarnessProcessResult(
        ["checkdiff", function],
        0 if match else 1,
        json.dumps(
            {
                "function": function,
                "match": match,
                "fuzzy_match_percent": percent,
                "classification": {"primary": primary},
            }
        ),
        "",
    )


def _install_cli_harvest_fakes(
    monkeypatch,
    tmp_path: Path,
    payload: dict | None = None,
) -> tuple[Path, list[list[str]]]:
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        return HarnessProcessResult(
            command=args,
            returncode=0,
            stdout=json.dumps(
                payload
                or {
                    "variants": [
                        {
                            "status": "ok",
                            "source_path": str(tmp_path / "candidate.c"),
                            "final_match_percent": 100.0,
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(harvest_cli, "HARVEST_RUNNER", runner)
    return repo_root, calls


def test_cli_missing_queue_exits_nonzero_with_clear_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "missing-bucket",
            "--taxonomy-dir",
            str(tmp_path / "queues"),
        ],
    )

    assert result.exit_code != 0
    assert "queue is missing" in result.output.lower()
    assert "missing-bucket.tsv" in result.output


def test_cli_explicit_ledger_writes_file_and_prints_status_counts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app

    repo_root, calls = _install_cli_harvest_fakes(monkeypatch, tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])
    ledger_path = tmp_path / "ledger.json"

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--ledger",
            str(ledger_path),
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls
    assert ledger_path.exists()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["work_bucket"] == "stack-local-layout"
    assert ledger["summary"]["by_status"] == {"validated": 1}
    assert str(repo_root) in ledger["results"][0]["source_file"]
    assert str(ledger_path) in result.output
    assert "status counts: validated=1" in result.output


def test_cli_json_output_is_parseable_ledger(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app

    _install_cli_harvest_fakes(monkeypatch, tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])
    ledger_path = tmp_path / "ledger.json"

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--ledger",
            str(ledger_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    ledger = json.loads(result.output)
    assert ledger["schema_version"] == 1
    assert ledger["summary"]["by_status"] == {"validated": 1}
    assert ledger == json.loads(ledger_path.read_text(encoding="utf-8"))


def test_cli_compose_passes_flag_and_outputs_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])
    ledger_path = tmp_path / "ledger.json"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    def fake_run_harvest(*args, **kwargs):
        calls.append(dict(kwargs))
        ledger = {
            "schema_version": 1,
            "work_bucket": args[0],
            "summary": {"by_status": {"validated": 1}},
            "results": [],
        }
        Path(kwargs["ledger_path"]).write_text(json.dumps(ledger), encoding="utf-8")
        return ledger

    monkeypatch.setattr(harvest_cli, "run_harvest", fake_run_harvest)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--ledger",
            str(ledger_path),
            "--compose",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["schema_version"] == 1
    assert calls[0]["compose"] is True


def test_cli_default_ledger_path_uses_repo_build_harvest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app

    repo_root, _ = _install_cli_harvest_fakes(monkeypatch, tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    ledgers = list((repo_root / "build" / "harvest").glob("stack-local-layout-*.json"))
    assert len(ledgers) == 1
    assert re.fullmatch(r"stack-local-layout-\d{8}-\d{6}\.json", ledgers[0].name)
    assert str(ledgers[0]) in result.output


def test_cli_default_ledger_path_avoids_same_second_collision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app

    repo_root, _ = _install_cli_harvest_fakes(monkeypatch, tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])

    first = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
        ],
    )
    second = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
        ],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    ledgers = sorted((repo_root / "build" / "harvest").glob("stack-local-layout-*.json"))
    assert len(ledgers) == 2
    assert ledgers[0] != ledgers[1]
    assert re.fullmatch(r"stack-local-layout-\d{8}-\d{6}(?:-\d{3})?\.json", ledgers[0].name)
    assert re.fullmatch(r"stack-local-layout-\d{8}-\d{6}(?:-\d{3})?\.json", ledgers[1].name)


def test_cli_invalid_target_map_exits_with_input_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app

    _install_cli_harvest_fakes(monkeypatch, tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])
    target_map = tmp_path / "bad-target-map.json"
    target_map.write_text("[", encoding="utf-8")

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--target-map",
            str(target_map),
        ],
    )

    assert result.exit_code == 2
    assert "harvest input error:" in result.output
    assert "Traceback" not in result.output
    assert "issue report" not in result.output


def test_load_queue_rows_filters_by_min_match_and_limit(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row("below", match_percent="80.0"),
            _row("first", match_percent="98.0"),
            _row("second", match_percent="99.5"),
        ],
    )

    rows = load_queue_rows(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
        min_match=90.0,
        limit=1,
    )

    assert [row.function for row in rows] == ["first"]
    assert rows[0].source_file == repo_root / "src" / "melee/demo.c"


def test_load_queue_rows_limit_zero_processes_no_rows(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("first", match_percent="98.0")])

    rows = load_queue_rows(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
        min_match=90.0,
        limit=0,
    )

    assert rows == []


def test_resolve_source_file_rejects_paths_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.c"
    outside.write_text("void outside(void) {}\n", encoding="utf-8")

    assert resolve_source_file(repo_root, str(outside)) is None
    assert resolve_source_file(repo_root, "../outside.c") is None


def test_load_queue_rows_merges_target_map_by_function(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register.tsv"
    _write_queue(queue, [_row("reg_fn", headline_tool="register-search")])
    target_map_path = tmp_path / "targets.json"
    target_map_path.write_text(
        json.dumps({"reg_fn": {"harness": "coalesce-search", "target": "37=40"}}),
        encoding="utf-8",
    )

    rows = load_queue_rows(
        queue,
        work_bucket="register",
        repo_root=repo_root,
        target_map=load_target_map(target_map_path),
    )

    assert rows[0].facts == {"harness": "coalesce-search", "target": "37=40"}


def test_frame_transform_search_command_is_built_from_frame_row(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    calls, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(tmp_path / "candidate.c"),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        apply=False,
    )

    assert calls == [
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "demo_fn",
            "--source-file",
            str(repo_root / "src" / "melee/demo.c"),
            "--compile-probes",
            "--json",
            "--max-probes",
            "8",
            "--timeout",
            "120",
        ]
    ]
    assert ledger["results"][0]["status"] == "validated"


def test_register_target_map_selects_coalesce_search(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register.tsv"
    _write_queue(queue, [_row("reg_fn", headline_tool="register-search")])
    calls, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "retained_source_path": str(tmp_path / "candidate.c"),
                    "match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "register",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"reg_fn": {"harness": "coalesce-search", "target": "37=40"}},
        runner=runner,
    )

    assert calls == [
        [
            "debug",
            "coalesce-search",
            "-f",
            "reg_fn",
            "--target",
            "37=40",
            "--source-file",
            str(repo_root / "src" / "melee/demo.c"),
            "--compile-probes",
            "--json",
            "--max-probes",
            "8",
            "--timeout",
            "120",
        ]
    ]
    assert ledger["results"][0]["harness"] == "coalesce-search"
    assert ledger["results"][0]["status"] == "validated"


def test_select_order_search_includes_class_id(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register.tsv"
    _write_queue(queue, [_row("reg_fn", headline_tool="register-search")])
    calls, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(tmp_path / "candidate.c"),
                    "objective": {"match_percent": 100.0},
                }
            ]
        }
    )

    run_harvest(
        "register",
        repo_root=repo_root,
        queue_path=queue,
        target_map={
            "reg_fn": {
                "harness": "select-order-search",
                "target": "43<33",
                "class_id": 1,
            }
        },
        runner=runner,
    )

    assert calls[0] == [
        "debug",
        "select-order-search",
        "-f",
        "reg_fn",
        "--target",
        "43<33",
        "--class",
        "1",
        "--source-file",
        str(repo_root / "src" / "melee/demo.c"),
        "--compile-probes",
        "--json",
        "--max-probes",
        "8",
        "--timeout",
        "120",
    ]


def test_indexed_struct_primary_selects_indexed_search(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "indexed-struct-search"


def test_indexed_struct_source_actionability_selects_indexed_search(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "indexed-struct-search"


def test_indexed_struct_target_map_harness_selects_indexed_search(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        target_map={"demo_fn": {"harness": "indexed-struct-search"}},
    )

    assert select_harness(rows[0]) == "indexed-struct-search"


def test_indexed_struct_command_text_selects_indexed_search(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
        next_command="melee-agent debug mutate indexed-struct-search -f demo_fn",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "indexed-struct-search"


def test_indexed_struct_harvest_builds_indexed_search_command(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    calls, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(tmp_path / "candidate.c"),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[0][:5] == [
        "debug",
        "mutate",
        "indexed-struct-search",
        "-f",
        "demo_fn",
    ]
    assert "--score-match-percent" in calls[0]
    assert ledger["results"][0]["harness"] == "indexed-struct-search"
    assert ledger["results"][0]["status"] == "validated"


def test_data_symbol_relocation_current_queue_row_selects_name_magic_harness(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(
        queue,
        [_name_magic_row("demo_fn", primary="data-symbol-or-relocation")],
    )

    rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "name-magic-source-declarations"


def test_data_symbol_relocation_normalized_primary_selects_name_magic_harness(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])

    rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "name-magic-source-declarations"


def test_name_magic_harvest_builds_source_declarations_command(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    calls, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(tmp_path / "candidate.c"),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        timeout=9,
        max_probes=3,
    )

    assert calls == [
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "demo_fn",
            "--source-file",
            str(repo_root / "src" / "melee/demo.c"),
            "--compile-probes",
            "--score-match-percent",
            "--json",
            "--max-probes",
            "3",
            "--timeout",
            "9",
        ]
    ]
    assert ledger["results"][0]["harness"] == "name-magic-source-declarations"
    assert ledger["results"][0]["status"] == "validated"


def test_name_magic_gate_accepts_match_percent_without_final_score(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    calls, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(tmp_path / "candidate.c"),
                    "match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert calls[0][2] == "name-magic-source-declarations"
    assert result["status"] == "validated"
    assert result["final_match_percent"] == 100.0


def test_name_magic_gate_requires_no_name_magic_match_true(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-name-magic-candidate",
                "reason": "no source candidate reached a true --no-name-magic match",
            },
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(tmp_path / "candidate.c"),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": False,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "no-name-magic-candidate"


def test_name_magic_gate_requires_validated_stop_condition(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-name-magic-candidate",
                "reason": "candidate was not validated",
            },
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(tmp_path / "candidate.c"),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "no-name-magic-candidate"


def test_name_magic_propagates_blocked_stop_condition(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "blocker": "sdata2-pool-order-dependent",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "sdata2-pool-order-dependent",
                "reason": "anonymous pool order depends on earlier TU state",
            },
            "variants": [],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "sdata2-pool-order-dependent"
    assert result["reason"] == "anonymous pool order depends on earlier TU state"


def test_compose_dry_run_stops_after_first_candidate_and_records_not_observed(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "composite.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void demo_fn(void) {}\n", encoding="utf-8")
    calls, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
        target_map={
            "demo_fn": {
                "harnesses": [
                    "indexed-struct-search",
                    "frame-transform-search",
                ]
            }
        },
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: _match_process(
            function,
            match=False,
            percent=90.0,
            primary="indexed-struct-pointer-materialization",
        ),
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "validated"
    assert result["harness"] == "composed"
    assert result["details"]["stop_reason"] == "dry-run-first-candidate-layer"
    assert result["details"]["not_observed_layers"] == ["frame-transform-search"]
    assert [call[2] for call in calls] == ["indexed-struct-search"]


def test_compose_apply_preserves_sub100_improvement_and_continues_to_match(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("int demo_fn(void) {\n    return 1;\n}\n", encoding="utf-8")
    indexed_candidate = tmp_path / "indexed.c"
    indexed_candidate.write_text(
        "int demo_fn(void) {\n    return 2;\n}\n",
        encoding="utf-8",
    )
    frame_candidate = tmp_path / "frame.c"
    frame_candidate.write_text(
        "int demo_fn(void) {\n    return 3;\n}\n",
        encoding="utf-8",
    )
    queue = tmp_path / "queues" / "composite.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[2] == "indexed-struct-search":
            payload = {
                "variants": [
                    {
                        "status": "ok",
                        "source_retained": str(indexed_candidate),
                        "final_match_percent": 95.0,
                    }
                ]
            }
        else:
            payload = {
                "variants": [
                    {
                        "status": "ok",
                        "source_path": str(frame_candidate),
                        "final_match_percent": 100.0,
                    }
                ]
            }
        return HarnessProcessResult(args, 0, json.dumps(payload), "")

    match_payloads = iter(
        [
            _match_process(
                "demo_fn",
                match=False,
                percent=90.0,
                primary="indexed-struct-pointer-materialization",
            ),
            _match_process(
                "demo_fn",
                match=False,
                percent=95.0,
                primary="stack-layout",
            ),
            _match_process(
                "demo_fn",
                match=False,
                percent=95.0,
                primary="stack-layout",
            ),
            _match_process("demo_fn", match=True, percent=100.0, primary="match"),
        ]
    )

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
        target_map={
            "demo_fn": {
                "harnesses": [
                    "indexed-struct-search",
                    "frame-transform-search",
                ]
            }
        },
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: next(match_payloads),
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 0, "", ""
        ),
        apply=True,
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "already-matched"
    assert result["harness"] == "composed"
    assert result["details"]["stop_reason"] == "matched-after-layers"
    assert [call[2] for call in calls] == [
        "indexed-struct-search",
        "frame-transform-search",
    ]
    assert result["details"]["layers"][0]["details"]["layer_outcome"] == (
        "verified-improvement"
    )
    assert target.read_text(encoding="utf-8") == (
        "int demo_fn(void) {\n    return 3;\n}\n"
    )


def test_compose_apply_rolls_back_sub100_candidate_without_improvement(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "indexed.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "composite.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 89.0,
                }
            ]
        }
    )
    match_payloads = iter(
        [
            _match_process(
                "demo_fn",
                match=False,
                percent=90.0,
                primary="indexed-struct-pointer-materialization",
            ),
            _match_process(
                "demo_fn",
                match=False,
                percent=89.0,
                primary="indexed-struct-pointer-materialization",
            ),
        ]
    )

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"demo_fn": {"harnesses": ["indexed-struct-search"]}},
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: next(match_payloads),
        apply=True,
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "apply-validation-failed"
    assert result["details"]["layers"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original


def test_compose_apply_rolls_back_sub100_candidate_after_invalid_checkdiff_json(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "indexed.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "composite.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 92.0,
                }
            ]
        }
    )
    match_payloads = iter(
        [
            _match_process(
                "demo_fn",
                match=False,
                percent=90.0,
                primary="indexed-struct-pointer-materialization",
            ),
            HarnessProcessResult(["checkdiff", "demo_fn"], 1, "not-json", "boom"),
            _match_process(
                "demo_fn",
                match=False,
                percent=90.0,
                primary="indexed-struct-pointer-materialization",
            ),
        ]
    )

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"demo_fn": {"harnesses": ["indexed-struct-search"]}},
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: next(match_payloads),
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 0, "", ""
        ),
        apply=True,
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "apply-validation-failed"
    assert result["details"]["layers"][0]["reason"] == (
        "candidate did not verify a strict post-apply improvement"
    )
    assert target.read_text(encoding="utf-8") == original


def test_compose_unsupported_future_harness_bubbles_to_top(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "composite.tsv"
    _write_queue(queue, [_row("demo_fn")])

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"demo_fn": {"harnesses": ["control-flow-search"]}},
        match_checker=lambda function, *, cwd, timeout: _match_process(
            function,
            match=False,
            percent=90.0,
            primary="branch-or-control-flow-shape",
        ),
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "unsupported"
    assert result["blocker"] == "unsupported-harness"
    assert result["details"]["layers"][0]["harness"] == "control-flow-search"
    assert result["details"]["layers"][0]["blocker"] == "unsupported-harness"


def test_compose_missing_register_target_bubbles_to_top(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "composite.tsv"
    _write_queue(queue, [_row("demo_fn")])

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"demo_fn": {"harnesses": ["coalesce-search"]}},
        match_checker=lambda function, *, cwd, timeout: _match_process(
            function,
            match=False,
            percent=90.0,
            primary="register-allocation",
        ),
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "missing-register-target"
    assert result["details"]["layers"][0]["harness"] == "coalesce-search"
    assert result["details"]["layers"][0]["blocker"] == "missing-register-target"


def test_missing_register_target_returns_stable_blocker(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register.tsv"
    _write_queue(queue, [_row("reg_fn", headline_tool="register-search")])

    ledger = run_harvest(
        "register",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"reg_fn": {"harness": "coalesce-search"}},
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "missing-register-target"


def test_unknown_harness_returns_stable_blocker(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "unknown.tsv"
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                headline_tool="unknown-tool",
                source_actionability="",
                frame_closability_tier="",
            )
        ],
    )

    request = HarvestRequest(
        function="fn",
        work_bucket="bucket",
        match_percent=99.0,
        file_path="melee/demo.c",
        headline_tool="unknown-tool",
        source_file=Path("demo.c"),
    )
    ledger = run_harvest("unknown", repo_root=repo_root, queue_path=queue)

    assert select_harness(request) is None
    assert ledger["results"][0]["status"] == "unsupported"
    assert ledger["results"][0]["blocker"] == "unsupported-harness"


def test_score_extraction_accepts_supported_shapes() -> None:
    assert extract_candidate_score({"final_match_percent": 100.0}) == 100.0
    assert extract_candidate_score({"match_percent": "99.9"}) == 99.9
    assert extract_candidate_score({"objective": {"match_percent": 98}}) == 98.0
    assert extract_candidate_score({"objective": {}}) is None


def test_best_validated_candidate_requires_true_100_and_source() -> None:
    good = {
        "status": "ok",
        "source_path": "candidate.c",
        "final_match_percent": 100.0,
    }

    assert best_validated_candidate({"variants": [{"status": "ok"}]}) is None
    assert best_validated_candidate({"variants": [good]}) == good
    assert best_validated_candidate(
        {
            "ranked_variants": [
                {
                    "status": "ok",
                    "source_path": "candidate.c",
                    "final_match_percent": 99.999,
                }
            ]
        }
    ) is None
    assert best_validated_candidate(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": "candidate.pcdump.txt",
                    "final_match_percent": 100.0,
                }
            ]
        }
    ) is None


def test_best_validated_candidate_accepts_source_retained_but_rejects_txt_path() -> None:
    retained = {
        "status": "ok",
        "path": "candidate.pcdump.txt",
        "source_retained": "candidate.c",
        "final_match_percent": 100.0,
    }
    pcdump_only = {
        "status": "ok",
        "path": "candidate.pcdump.txt",
        "final_match_percent": 100.0,
    }

    assert best_validated_candidate({"variants": [retained]}) == retained
    assert best_validated_candidate({"variants": [pcdump_only]}) is None


def test_frame_harness_without_100_candidate_records_no_validated_candidate(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(tmp_path / "candidate.c"),
                    "final_match_percent": 99.9,
                }
            ]
        }
    )

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert ledger["results"][0]["status"] == "no_match"
    assert ledger["results"][0]["blocker"] == "no-validated-candidate"


def test_harvest_propagates_indexed_search_stable_blocker(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "blocker": "no-safe-materialized-pointer",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "no-safe-materialized-pointer",
                "reason": "source scan found no safe materialized pointer",
            },
            "variants": [],
        }
    )

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "no-safe-materialized-pointer"
    assert result["reason"] == "source scan found no safe materialized pointer"


def test_harness_failures_and_invalid_json_have_stable_blockers(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("bad_exit"), _row("bad_json")])

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        if args[4] == "bad_exit":
            return HarnessProcessResult(args, 1, "out", "err")
        return HarnessProcessResult(args, 0, "not json", "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert [result["blocker"] for result in ledger["results"]] == [
        "harness-exit-nonzero",
        "harness-invalid-json",
    ]


def test_missing_source_file_is_blocked_before_harness(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("missing_fn")])

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "missing-source-file"


def test_ledger_summary_counts_status_harness_tier_and_blocker() -> None:
    results = [
        {
            "status": "validated",
            "harness": "frame-transform-search",
            "frame_closability_tier": "current-tools-padstack",
            "source_actionability": "source-reachable-candidate",
            "blocker": None,
        },
        {
            "status": "blocked",
            "harness": "coalesce-search",
            "frame_closability_tier": "",
            "source_actionability": "register-source",
            "blocker": "missing-register-target",
        },
        {
            "status": "unsupported",
            "harness": None,
            "frame_closability_tier": "",
            "source_actionability": "",
            "blocker": "unsupported-harness",
        },
    ]

    assert summarize_ledger(results) == {
        "total_rows": 3,
        "processed": 3,
        "by_status": {"validated": 1, "blocked": 1, "unsupported": 1},
        "by_harness": {
            "frame-transform-search": 1,
            "coalesce-search": 1,
            "unsupported": 1,
        },
        "by_tier": {
            "current-tools-padstack": 1,
            "register-source": 1,
            "unclassified": 1,
        },
        "by_blocker": {
            "missing-register-target": 1,
            "unsupported-harness": 1,
        },
    }


def test_write_ledger_adds_schema_version_and_summary(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger = write_ledger(
        ledger_path,
        work_bucket="bucket",
        started_at="2026-06-04T00:00:00Z",
        finished_at="2026-06-04T00:00:01Z",
        apply=False,
        min_match=90.0,
        limit=5,
        taxonomy_queue=tmp_path / "queue.tsv",
        target_map_path=None,
        results=[
            {
                "function": "fn",
                "status": "validated",
                "harness": "frame-transform-search",
                "frame_closability_tier": "tier",
                "source_actionability": "",
                "blocker": None,
            }
        ],
    )

    on_disk = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger == on_disk
    assert on_disk["schema_version"] == 1
    assert on_disk["summary"]["by_status"] == {"validated": 1}


def test_apply_replaces_only_target_function_when_validation_passes(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        textwrap.dedent(
            """\
            int demo_fn(void) {
                return 1;
            }

            int sibling(void) {
                return 7;
            }
            """
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text(
        textwrap.dedent(
            """\
            int demo_fn(void) {
                return 2;
            }

            int extra(void) {
                return 9;
            }
            """
        ),
        encoding="utf-8",
    )
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 0, "", ""
        ),
        apply=True,
    )

    assert ledger["results"][0]["status"] == "applied"
    assert target.read_text(encoding="utf-8") == textwrap.dedent(
        """\
        int demo_fn(void) {
            return 2;
        }

        int sibling(void) {
            return 7;
        }
        """
    )


def test_apply_skips_already_matched_row_before_running_harness(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        raise AssertionError("already-matched rows should not run the harness")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 0, "match=true\n", ""
        ),
        apply=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "already-matched"
    assert result["blocker"] is None
    assert result["applied"] is False
    assert result["reason"] == "function already matches; stale queue row skipped"


def test_indexed_struct_apply_uses_existing_function_only_replacement(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = textwrap.dedent(
        """\
        static int file_local = 3;

        int demo_fn(void) {
            return 1;
        }

        int sibling(void) {
            return file_local + 7;
        }
        """
    )
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 0, "", ""
        ),
        apply=True,
    )

    assert ledger["results"][0]["status"] == "applied"
    assert ledger["results"][0]["harness"] == "indexed-struct-search"
    assert target.read_text(encoding="utf-8") == textwrap.dedent(
        """\
        static int file_local = 3;

        int demo_fn(void) {
            return 2;
        }

        int sibling(void) {
            return file_local + 7;
        }
        """
    )


def test_indexed_struct_apply_rolls_back_when_validation_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original


def test_indexed_struct_apply_rolls_back_when_validation_is_interrupted(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    def interrupted_validator(function: str, *, cwd: Path, timeout: int):
        raise KeyboardInterrupt("stop")

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=interrupted_validator,
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original


def test_name_magic_rejects_non_c_retained_source_for_apply(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    target.write_text("int demo_fn(void) {\n    return 1;\n}\n", encoding="utf-8")
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        apply=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "declaration-apply-unsupported"
    assert target.read_text(encoding="utf-8") == "int demo_fn(void) {\n    return 1;\n}\n"


def test_name_magic_apply_replaces_entire_source_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = textwrap.dedent(
        """\
        static int keep_only_if_transfer(void) {
            return 11;
        }

        int demo_fn(void) {
            return 1;
        }
        """
    )
    target.write_text(original, encoding="utf-8")
    candidate_text = textwrap.dedent(
        """\
        static int replacement_file_local = 3;

        int demo_fn(void) {
            return replacement_file_local + 2;
        }
        """
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text(candidate_text, encoding="utf-8")
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 0, "", ""
        ),
        apply=True,
    )

    assert ledger["results"][0]["status"] == "applied"
    assert target.read_text(encoding="utf-8") == candidate_text


def test_name_magic_whole_file_apply_rolls_back_same_file_regression(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = textwrap.dedent(
        """\
        int demo_fn(void) {
            return 1;
        }

        int sibling(void) {
            return 7;
        }
        """
    )
    target.write_text(original, encoding="utf-8")
    report = repo_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "metadata": {"source_path": "src/melee/demo.c"},
                        "functions": [
                            {"name": "demo_fn", "fuzzy_match_percent": 99.0},
                            {"name": "sibling", "fuzzy_match_percent": 100.0},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text(
        textwrap.dedent(
            """\
            int demo_fn(void) {
                return 2;
            }

            int sibling(void) {
                return 9;
            }
            """
        ),
        encoding="utf-8",
    )
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    def validator(
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        if function == "sibling":
            return HarnessProcessResult(["checkdiff", function], 1, "", "mismatch")
        return HarnessProcessResult(["checkdiff", function], 0, "", "")

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=validator,
        apply=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "apply-validation-failed"
    assert result["reason"] == "post-apply regression guard failed"
    assert target.read_text(encoding="utf-8") == original


def test_name_magic_whole_file_apply_rolls_back_when_validation_fails(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original


def test_name_magic_whole_file_apply_rolls_back_when_validation_is_interrupted(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )

    def interrupted_validator(function: str, *, cwd: Path, timeout: int):
        raise KeyboardInterrupt("stop")

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=interrupted_validator,
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original


def test_name_magic_default_validator_and_match_checker_use_no_name_magic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True)
    target.write_text("int demo_fn(void) {\n    return 1;\n}\n", encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(
        {
            "stop_condition": {"kind": "validated"},
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "final_match_percent": 100.0,
                    "no_name_magic_match": True,
                }
            ],
        }
    )
    subprocess_calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        subprocess_calls.append(command)
        if "--format" in command:
            return subprocess.CompletedProcess(command, 1, '{"match": false}', "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harvest_module.subprocess, "run", fake_run)

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        apply=True,
    )

    checkdiff_calls = [
        command for command in subprocess_calls if "tools/checkdiff.py" in command
    ]
    assert ledger["results"][0]["status"] == "applied"
    assert len(checkdiff_calls) == 2
    assert all("--no-name-magic" in command for command in checkdiff_calls)


def test_apply_rolls_back_when_same_file_matched_function_regresses(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = textwrap.dedent(
        """\
        int demo_fn(void) {
            return 1;
        }

        int sibling(void) {
            return 7;
        }
        """
    )
    target.write_text(original, encoding="utf-8")
    report = repo_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "metadata": {"source_path": "src/melee/demo.c"},
                        "functions": [
                            {
                                "name": "demo_fn",
                                "fuzzy_match_percent": 99.0,
                            },
                            {
                                "name": "sibling",
                                "fuzzy_match_percent": 100.0,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    def validator(
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        if function == "sibling":
            return HarnessProcessResult(["checkdiff", function], 1, "", "mismatch")
        return HarnessProcessResult(["checkdiff", function], 0, "", "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        validator=validator,
        apply=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "apply-validation-failed"
    assert result["reason"] == "post-apply regression guard failed"
    assert target.read_text(encoding="utf-8") == original


def test_apply_rolls_back_when_validation_fails(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        validator=lambda function, *, cwd, timeout: HarnessProcessResult(
            ["checkdiff", function], 1, "", "mismatch"
        ),
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original


def test_apply_rolls_back_when_validation_is_interrupted(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    fixed_temp = target.with_suffix(target.suffix + ".tmp")
    fixed_temp.write_text("do not clobber\n", encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int demo_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    def interrupted_validator(
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        raise KeyboardInterrupt("stop")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        validator=interrupted_validator,
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-validation-failed"
    assert target.read_text(encoding="utf-8") == original
    assert fixed_temp.read_text(encoding="utf-8") == "do not clobber\n"


def test_apply_transfer_fails_when_candidate_lacks_function(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "int demo_fn(void) {\n    return 1;\n}\n"
    target.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text("int other_fn(void) {\n    return 2;\n}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "status": "ok",
                    "source_path": str(candidate),
                    "final_match_percent": 100.0,
                }
            ]
        }
    )

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
        apply=True,
    )

    assert ledger["results"][0]["status"] == "blocked"
    assert ledger["results"][0]["blocker"] == "apply-transfer-failed"
    assert target.read_text(encoding="utf-8") == original
