from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

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
