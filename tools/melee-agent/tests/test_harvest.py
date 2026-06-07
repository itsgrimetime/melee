from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

import src.harvest as harvest_module
from src.harvest import (
    HarnessProcessResult,
    HarvestFilters,
    HarvestRequest,
    best_validated_candidate,
    extract_candidate_score,
    load_queue_rows,
    load_target_map,
    preview_harvest_queue,
    resolve_source_file,
    run_harvest,
    select_harness,
    summarize_harvest_ledgers,
    summarize_ledger,
    write_ledger,
)

cli_runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[3]

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
    "name_magic_blocker",
    "name_magic_stop_kind",
    "name_magic_probe_count",
    "name_magic_reason",
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


def write_minimal_taxonomy_queue(taxonomy_root: Path, status: dict | None) -> Path:
    queues = taxonomy_root / "queues"
    queues.mkdir(parents=True)
    queue = queues / "signature-call-type.tsv"
    queue.write_text(
        "match_percent\tfunction\tprimary\tsubcategory\t"
        "source_actionability\theadline_tool\tfile_path\tnext_command\n"
        "99.0\tsig_fn\tsignature-type-mismatch\tcall-shape-or-prototype\t"
        "current-tools-signature-audit\tdebug-suggest-signatures\t"
        "melee/demo/demo.c\t"
        "melee-agent debug suggest signatures -f sig_fn "
        "--source-file src/melee/demo/demo.c --json\n",
        encoding="utf-8",
    )
    (taxonomy_root / "taxonomy.records.jsonl").write_text("", encoding="utf-8")
    if status is not None:
        (taxonomy_root / "run-status.json").write_text(
            json.dumps(status),
            encoding="utf-8",
        )
    return queue


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


def _structural_row(
    function: str,
    *,
    match_percent: str = "99.0",
    headline_tool: str = "extract-opseq-xrefs",
    source_actionability: str = "structural-rebuild",
    next_command: str = "",
) -> dict[str, str]:
    row = _row(
        function,
        match_percent=match_percent,
        headline_tool=headline_tool,
        source_actionability=source_actionability,
        frame_closability_tier="",
        next_command=next_command,
    )
    row["primary"] = "control-flow-source-shape"
    row["subcategory"] = "branch-or-control-flow-shape"
    return row


def _allocator_row(
    function: str,
    *,
    file_path: str = "melee/demo.c",
    headline_tool: str = "mwcc-debug",
    source_actionability: str = "pcdump-proof-needed",
    next_command: str | None = None,
) -> dict[str, str]:
    row = _row(
        function,
        file_path=file_path,
        headline_tool=headline_tool,
        source_actionability=source_actionability,
        frame_closability_tier="",
        next_command=(
            next_command
            if next_command is not None
            else f"melee-agent debug dump local src/{file_path} --function {function}"
        ),
    )
    row["primary"] = "register-allocator"
    row["subcategory"] = "register-allocator"
    return row


def _allocator_triage_payload(
    *,
    status: str = "needs-move",
    unit: str = "melee/demo",
    targets: list[dict[str, str]] | None = None,
    force_vector: str | None = "r26=r31",
    force_vector_runnable: bool | None = True,
    force_vector_recommended: bool | None = True,
    force_vector_conflicts: list[str] | None = None,
) -> dict:
    return {
        "target_vector_actionability": {
            "status": status,
            "summary": f"{status} summary",
            "next_step": f"{status} next step",
        },
        "force_vector": force_vector,
        "force_vector_runnable": force_vector_runnable,
        "force_vector_recommended": force_vector_recommended,
        "force_phys_csv": "r26,r31",
        "force_vector_conflicts": (
            force_vector_conflicts if force_vector_conflicts is not None else []
        ),
        "unit": unit,
        "targets": targets if targets is not None else [{"from": "r26", "to": "r31"}],
        "results": [{"target": "r26=r31", "status": "ok"}],
    }


def _force_vector_verify_payload(
    *,
    union_match: bool = False,
    probes: list[dict] | None = None,
) -> dict:
    return {
        "ran": True,
        "probe_count": 1 + len(probes or []),
        "entries": [
            {
                "raw": "class0:ig36:phys=r6",
                "kind": "force_phys",
                "class_id": 0,
                "ig_idx": 36,
                "phys": 6,
            }
        ],
        "union": {
            "label": "union",
            "ordinal": None,
            "entries": [
                {
                    "raw": "class0:ig36:phys=r6",
                    "kind": "force_phys",
                    "class_id": 0,
                    "ig_idx": 36,
                    "phys": 6,
                }
            ],
            "returncode": 0,
            "match": union_match,
            "status": "match" if union_match else "no_match",
            "stdout_tail": "[diff] MATCH" if union_match else "diff remained",
            "stderr_tail": "",
        },
        "probes": probes or [],
    }


def _install_fresh_pcdump_cache(monkeypatch, repo_root: Path) -> None:
    def lookup(_repo: Path, unit: str):
        return harvest_module.pcdump_cache.CacheEntry(
            path=harvest_module.pcdump_cache.cache_path(repo_root, unit),
            source_path=repo_root / "src" / f"{unit}.c",
            fresh=True,
        )

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lookup)


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


def test_cli_parses_harvest_filters_and_forwards_to_run_harvest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(
        taxonomy_dir / "structural-reconstruction.tsv",
        [
            _structural_row(
                "demo_fn",
                headline_tool="control-flow-shape-search",
                source_actionability="structural-rebuild",
            )
        ],
    )
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)
    calls: list[dict[str, object]] = []

    def fake_run_harvest(*args, **kwargs):
        calls.append(dict(kwargs))
        ledger = {
            "schema_version": 1,
            "work_bucket": args[0],
            "summary": {"by_status": {}},
            "results": [],
            "filters": kwargs["filters"].to_dict(),
        }
        Path(kwargs["ledger_path"]).write_text(json.dumps(ledger), encoding="utf-8")
        return ledger

    monkeypatch.setattr(harvest_cli, "run_harvest", fake_run_harvest)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "structural-reconstruction",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--where",
            "headline_tool=control-flow-shape-search",
            "--where",
            "source_actionability=structural-rebuild",
            "--exclude-source-actionability",
            "backend-ceiling,generator-gated",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    filters = calls[0]["filters"]
    assert filters.to_dict() == {
        "exclude_source_actionability": [
            "backend-ceiling",
            "generator-gated",
        ],
        "where": {
            "headline_tool": ["control-flow-shape-search"],
            "source_actionability": ["structural-rebuild"],
        },
    }


def test_cli_rejects_malformed_where_filter(monkeypatch, tmp_path: Path) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(taxonomy_dir / "stack-local-layout.tsv", [_row("demo_fn")])
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--where",
            "source_actionability",
        ],
    )

    assert result.exit_code == 2
    assert "harvest input error:" in result.output
    assert "FIELD=VALUE" in result.output


def test_cli_harvest_preview_json_does_not_run_or_write_ledger(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(
        taxonomy_dir / "structural-reconstruction.tsv",
        [_structural_row("demo_fn")],
    )
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)
    monkeypatch.setattr(
        harvest_cli,
        "_default_ledger_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("preview must not allocate a ledger path")
        ),
    )

    def fail_run_harvest(*args, **kwargs):
        raise AssertionError("preview must not run harvest")

    monkeypatch.setattr(harvest_cli, "run_harvest", fail_run_harvest)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "structural-reconstruction",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--where",
            "source_actionability=structural-rebuild",
            "--preview",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["counts"]["matching_rows"] == 1
    assert payload["sample"][0]["function"] == "demo_fn"
    assert list((repo_root / "build" / "harvest").glob("*.json")) == []


def test_cli_harvest_taxonomy_dir_accepts_artifact_root_with_queues(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_root = tmp_path / "function-taxonomy"
    queue_dir = taxonomy_root / "queues"
    _write_queue(
        queue_dir / "indexed-struct-pointer.tsv",
        [_structural_row("demo_fn")],
    )
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "indexed-struct-pointer",
            "--taxonomy-dir",
            str(taxonomy_root),
            "--preview",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["taxonomy_queue"] == str(
        queue_dir / "indexed-struct-pointer.tsv"
    )
    assert payload["sample"][0]["function"] == "demo_fn"


def test_cli_harvest_preview_text_shows_facets_and_sample(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_dir = tmp_path / "queues"
    _write_queue(
        taxonomy_dir / "stack-local-layout.tsv",
        [
            _row(
                "demo_fn",
                headline_tool="frame-transform-search",
                source_actionability="current-tools",
                next_command=(
                    "melee-agent debug mutate frame-transform-search -f demo_fn"
                ),
            )
        ],
    )
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--preview",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "preview: stack-local-layout" in result.output
    assert "matching=1" in result.output
    assert "headline_tool: frame-transform-search=1" in result.output
    assert "demo_fn" in result.output
    assert "harness=frame-transform-search" in result.output
    assert (
        "next_command=melee-agent debug mutate frame-transform-search -f demo_fn"
        in result.output
    )


def test_cli_filtered_harvest_zero_rows_fails_before_ledger(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.cli import app
    from src.cli import harvest as harvest_cli

    repo_root = _repo_with_source(tmp_path)
    taxonomy_dir = tmp_path / "queues"
    ledger_path = tmp_path / "empty.json"
    _write_queue(
        taxonomy_dir / "stack-local-layout.tsv",
        [_row("demo_fn", source_actionability="current-tools")],
    )
    monkeypatch.setattr(harvest_cli, "DEFAULT_MELEE_ROOT", repo_root)

    result = cli_runner.invoke(
        app,
        [
            "harvest",
            "stack-local-layout",
            "--taxonomy-dir",
            str(taxonomy_dir),
            "--ledger",
            str(ledger_path),
            "--where",
            "source_actionability=source-probe",
        ],
    )

    assert result.exit_code == 2
    assert "harvest input error:" in result.output
    assert "filters matched zero rows" in result.output
    assert not ledger_path.exists()


def test_summarize_harvest_ledgers_rolls_up_statuses_and_repeated_blockers(
    tmp_path: Path,
) -> None:
    ledger_a = tmp_path / "data-symbol.json"
    ledger_b = tmp_path / "structural.json"
    ledger_a.write_text(
        json.dumps(
            {
                "work_bucket": "data-symbol-relocation",
                "results": [
                    {
                        "function": "fn_a",
                        "work_bucket": "data-symbol-relocation",
                        "status": "applied",
                        "harness": "name-magic-source-declarations",
                        "blocker": None,
                        "candidate_path": "/tmp/fn_a.c",
                        "final_match_percent": 100.0,
                    },
                    {
                        "function": "fn_b",
                        "work_bucket": "data-symbol-relocation",
                        "status": "improved",
                        "harness": "name-magic-source-declarations",
                        "blocker": None,
                        "candidate_path": "/tmp/fn_b.c",
                        "final_match_percent": 99.7,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    ledger_b.write_text(
        json.dumps(
            {
                "work_bucket": "structural-reconstruction",
                "results": [
                    {
                        "function": "fn_c",
                        "work_bucket": "structural-reconstruction",
                        "status": "no_match",
                        "harness": "control-flow-shape-search",
                        "blocker": "no-control-flow-shape-candidate",
                    },
                    {
                        "function": "fn_d",
                        "work_bucket": "structural-reconstruction",
                        "status": "blocked",
                        "harness": "control-flow-shape-search",
                        "blocker": "no-control-flow-shape-candidate",
                    },
                    {
                        "function": "fn_e",
                        "work_bucket": "structural-reconstruction",
                        "status": "no_match",
                        "harness": "control-flow-shape-search",
                        "blocker": "no-control-flow-shape-candidate",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_harvest_ledgers([ledger_a, ledger_b])

    assert summary["ledger_count"] == 2
    assert summary["total_rows"] == 5
    assert summary["by_status"] == {
        "applied": 1,
        "blocked": 1,
        "improved": 1,
        "no_match": 2,
    }
    assert summary["by_work_bucket"] == {
        "data-symbol-relocation": 2,
        "structural-reconstruction": 3,
    }
    assert summary["retained_source_functions"] == ["fn_a", "fn_b"]
    assert summary["repeated_blockers"] == [
        {
            "blocker": "no-control-flow-shape-candidate",
            "count": 3,
            "functions": ["fn_c", "fn_d", "fn_e"],
            "harnesses": ["control-flow-shape-search"],
            "work_buckets": ["structural-reconstruction"],
        }
    ]
    assert summary["suggested_impact"] == "matched"


def test_summarize_harvest_ledgers_reports_filter_usage(tmp_path: Path) -> None:
    filtered = tmp_path / "filtered.json"
    raw = tmp_path / "raw.json"
    filtered.write_text(
        json.dumps(
            {
                "work_bucket": "structural-reconstruction",
                "filters": {
                    "where": {"headline_tool": ["control-flow-shape-search"]},
                    "exclude_source_actionability": ["backend-ceiling"],
                },
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    raw.write_text(
        json.dumps(
            {
                "work_bucket": "stack-local-layout",
                "filters": None,
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_harvest_ledgers([filtered, raw])

    assert summary["filtered_ledger_count"] == 1
    assert summary["raw_ledger_count"] == 1
    assert summary["filters"] == [
        {
            "count": 1,
            "filters": {
                "exclude_source_actionability": ["backend-ceiling"],
                "where": {"headline_tool": ["control-flow-shape-search"]},
            },
            "work_buckets": ["structural-reconstruction"],
        }
    ]


def test_summarize_harvest_ledgers_keeps_dry_run_improvements_out_of_retained_source(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "dry-run-data-symbol.json"
    ledger.write_text(
        json.dumps(
            {
                "work_bucket": "data-symbol-relocation",
                "apply": False,
                "applied_functions": [],
                "validated_functions": [],
                "results": [
                    {
                        "function": "un_80317A60",
                        "work_bucket": "data-symbol-relocation",
                        "status": "improved",
                        "harness": "name-magic-source-declarations",
                        "blocker": None,
                        "candidate_path": "/tmp/un_80317A60.c",
                        "final_match_percent": 92.4,
                        "applied": False,
                    },
                    {
                        "function": "fn_801AA854",
                        "work_bucket": "data-symbol-relocation",
                        "status": "improved",
                        "harness": "name-magic-source-declarations",
                        "blocker": None,
                        "candidate_path": "/tmp/fn_801AA854.c",
                        "final_match_percent": 91.2,
                        "applied": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_harvest_ledgers([ledger])

    assert summary["improved_functions"] == ["fn_801AA854", "un_80317A60"]
    assert summary["applied_functions"] == []
    assert summary["validated_functions"] == []
    assert summary["retained_source_functions"] == []
    assert summary["suggested_impact"] == "positive-candidate/no-retained-source"


def test_summarize_harvest_ledgers_keeps_allocator_diagnostic_matches_out_of_negative_evidence(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "allocator-diagnostic.json"
    ledger.write_text(
        json.dumps(
            {
                "work_bucket": "register-allocator",
                "results": [
                    {
                        "function": "ftCo_LightThrowDash_Phys",
                        "work_bucket": "register-allocator",
                        "status": "diagnostic_match",
                        "harness": "allocator-pcdump-triage",
                        "blocker": "allocator-force-vector-match",
                    },
                    {
                        "function": "un_803147C4",
                        "work_bucket": "register-allocator",
                        "status": "no_match",
                        "harness": "allocator-pcdump-triage",
                        "blocker": "allocator-force-vector-no-match",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_harvest_ledgers([ledger])

    assert summary["by_status"] == {"diagnostic_match": 1, "no_match": 1}
    assert summary["negative_evidence_functions"] == ["un_803147C4"]


def test_cli_harvest_summarize_outputs_json_without_running_harnesses(
    tmp_path: Path,
) -> None:
    from src.cli import app

    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "work_bucket": "stack-local-layout",
                "results": [
                    {
                        "function": "fn_a",
                        "work_bucket": "stack-local-layout",
                        "status": "validated",
                        "harness": "frame-transform-search",
                        "blocker": None,
                        "candidate_path": "/tmp/fn_a.c",
                    },
                    {
                        "function": "fn_b",
                        "work_bucket": "stack-local-layout",
                        "status": "no_match",
                        "harness": "frame-transform-search",
                        "blocker": "no-validated-candidate",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = cli_runner.invoke(app, ["harvest", "summarize", str(ledger), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ledger_count"] == 1
    assert payload["by_status"] == {"no_match": 1, "validated": 1}
    assert payload["retained_source_functions"] == ["fn_a"]
    assert payload["suggested_impact"] == "retained-source-improvement"


def test_cli_harvest_summarize_keeps_existing_harvest_command_shape(
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
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls
    assert ledger_path.exists()
    assert str(repo_root) in json.loads(ledger_path.read_text())["results"][0]["source_file"]


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


def test_load_queue_rows_applies_where_filters_before_limit(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    _write_queue(
        queue,
        [
            _row(
                "noise",
                headline_tool="manual-inspection",
                source_actionability="backend-ceiling",
            ),
            _row(
                "first_match",
                headline_tool="control-flow-shape-search",
                source_actionability="structural-rebuild",
            ),
            _row(
                "second_match",
                headline_tool="control-flow-shape-search",
                source_actionability="structural-rebuild",
            ),
        ],
    )

    rows = load_queue_rows(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
        limit=1,
        filters=HarvestFilters(
            where={"headline_tool": ("control-flow-shape-search",)}
        ),
    )

    assert [row.function for row in rows] == ["first_match"]


def test_load_queue_rows_ands_where_fields_and_ors_repeated_values(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    _write_queue(
        queue,
        [
            _row(
                "wrong_tool",
                headline_tool="manual-inspection",
                source_actionability="structural-rebuild",
            ),
            _row(
                "current_tools",
                headline_tool="control-flow-shape-search",
                source_actionability="current-tools",
            ),
            _row(
                "structural",
                headline_tool="control-flow-shape-search",
                source_actionability="structural-rebuild",
            ),
        ],
    )

    rows = load_queue_rows(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={
                "headline_tool": ("control-flow-shape-search",),
                "source_actionability": ("current-tools", "structural-rebuild"),
            }
        ),
    )

    assert [row.function for row in rows] == ["current_tools", "structural"]


def test_load_queue_rows_excludes_source_actionability_before_limit(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row("backend", source_actionability="backend-ceiling"),
            _row("generator", source_actionability="generator-gated"),
            _row("usable", source_actionability="current-tools"),
        ],
    )

    rows = load_queue_rows(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
        limit=1,
        filters=HarvestFilters(
            exclude_source_actionability=(
                "backend-ceiling",
                "generator-gated",
            )
        ),
    )

    assert [row.function for row in rows] == ["usable"]


def test_load_queue_rows_rejects_unknown_filter_field_even_with_zero_limit(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])

    with pytest.raises(ValueError, match="unknown harvest filter field"):
        load_queue_rows(
            queue,
            work_bucket="stack-local-layout",
            repo_root=repo_root,
            limit=0,
            filters=HarvestFilters(where={"missing": ("value",)}),
        )


def test_default_runner_uses_process_group_timeout_with_child_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, int, dict[str, str] | None]] = []

    def fake_process_group_runner(cmd, *, cwd, timeout, env=None):
        calls.append(([str(part) for part in cmd], cwd, timeout, env))
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    def fail_subprocess_run(*args, **kwargs):
        raise AssertionError("harvest runner must use process-group timeout")

    monkeypatch.setattr(
        harvest_module,
        "_run_with_process_group_timeout",
        fake_process_group_runner,
        raising=False,
    )
    monkeypatch.setattr(harvest_module.subprocess, "run", fail_subprocess_run)

    result = harvest_module._default_runner(
        ["debug", "dump", "local", "src/sysdolphin/baselib/particle.c"],
        cwd=tmp_path,
        timeout=45,
    )

    assert result.returncode == 0
    assert calls[0][0][:3] == [sys.executable, "-m", "src.cli"]
    assert calls[0][2] == 75
    assert calls[0][3] is not None
    assert float(calls[0][3]["MWCC_DEBUG_HANG_TIMEOUT"]) < 45


def test_default_runner_converts_timeout_to_process_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_process_group_runner(cmd, *, cwd, timeout, env=None):
        raise subprocess.TimeoutExpired(
            cmd,
            timeout,
            output="partial stdout",
            stderr="unsafe local pcdump lane",
        )

    monkeypatch.setattr(
        harvest_module,
        "_run_with_process_group_timeout",
        fake_process_group_runner,
        raising=False,
    )

    result = harvest_module._default_runner(
        ["debug", "dump", "local", "src/sysdolphin/baselib/particle.c"],
        cwd=tmp_path,
        timeout=45,
    )

    assert result.returncode == 124
    assert result.stdout == "partial stdout"
    assert "unsafe local pcdump lane" in result.stderr


def test_preview_harvest_queue_counts_facets_and_sample_before_limit(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    _write_queue(
        queue,
        [
            _structural_row(
                "below_threshold",
                match_percent="80.0",
                headline_tool="manual-inspection",
                source_actionability="structural-rebuild",
            ),
            _structural_row(
                "first_match",
                match_percent="97.0",
                headline_tool="extract-opseq-xrefs",
                source_actionability="structural-rebuild",
                next_command="melee-agent extract get first_match",
            ),
            _structural_row(
                "second_match",
                match_percent="98.0",
                headline_tool="extract-opseq-xrefs",
                source_actionability="structural-rebuild",
                next_command="melee-agent extract get second_match",
            ),
            _structural_row(
                "wrong_actionability",
                match_percent="99.0",
                headline_tool="manual-inspection",
                source_actionability="backend-ceiling",
            ),
        ],
    )

    preview = preview_harvest_queue(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
        min_match=90.0,
        limit=1,
        filters=HarvestFilters(
            where={"source_actionability": ("structural-rebuild",)}
        ),
        sample_limit=2,
    )

    assert preview["counts"] == {
        "queue_rows": 4,
        "eligible_rows": 3,
        "matching_rows": 2,
        "would_process_rows": 1,
        "terminal_attempt_rows": 0,
    }
    assert preview["facets"]["headline_tool"] == [
        {"value": "extract-opseq-xrefs", "count": 2}
    ]
    assert [row["function"] for row in preview["sample"]] == [
        "first_match",
        "second_match",
    ]
    assert preview["sample"][0]["harness"] == "control-flow-shape-search"
    assert preview["sample"][0]["next_command"] == (
        "melee-agent extract get first_match"
    )


def test_preview_harvest_queue_facets_name_magic_blocker(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    blocked = _name_magic_row("blocked_fn", primary="data-symbol-or-relocation")
    blocked["source_actionability"] = (
        "blocked-data-symbol-no-name-magic-candidate"
    )
    blocked["name_magic_blocker"] = "no-name-magic-candidate"
    blocked["name_magic_stop_kind"] = "blocked"
    blocked["name_magic_probe_count"] = "0"
    blocked["name_magic_reason"] = "no source-addressable relocation pair"
    ready = _name_magic_row("ready_fn", primary="data-symbol-or-relocation")
    ready["name_magic_probe_count"] = "1"
    _write_queue(queue, [blocked, ready])

    preview = preview_harvest_queue(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )

    assert preview["counts"]["matching_rows"] == 1
    assert [row["function"] for row in preview["sample"]] == ["ready_fn"]
    assert preview["near_miss_facets"]["name_magic_blocker"] == [
        {"value": "no-name-magic-candidate", "count": 1}
    ]


def test_indexed_malformed_rebucket_ledgers_are_applied_to_queue_preview(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    malformed = _row(
        "malformed_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    malformed["primary"] = "indexed-struct-pointer-materialization"
    ready = _row(
        "ready_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    ready["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [malformed, ready])
    ledger_dir = repo_root / "build" / "harvest"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "indexed-ledger.json").write_text(
        json.dumps(
            {
                "work_bucket": "indexed-struct-pointer",
                "results": [
                    {
                        "function": "malformed_fn",
                        "work_bucket": "indexed-struct-pointer",
                        "source_actionability": "candidate-generation-fidelity",
                        "blocker": "malformed-source-candidate",
                        "details": {
                            "source_actionability_rebucket": {
                                "from": "current-tools-indexed-pointer",
                                "to": "candidate-generation-fidelity",
                                "remove_from": "current-tools-indexed-pointer",
                                "blocker": "malformed-source-candidate",
                                "reason": (
                                    "candidate pcdump omitted the requested "
                                    "function"
                                ),
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    current_rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-indexed-pointer",)}
        ),
    )
    all_rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-indexed-pointer",)}
        ),
    )

    assert [row.function for row in current_rows] == ["ready_fn"]
    assert [row.source_actionability for row in all_rows] == [
        "candidate-generation-fidelity",
        "current-tools-indexed-pointer",
    ]
    assert select_harness(all_rows[0]) is None
    assert preview["counts"]["matching_rows"] == 1
    assert [row["function"] for row in preview["sample"]] == ["ready_fn"]
    assert preview["near_miss_facets"]["source_actionability"] == [
        {"value": "candidate-generation-fidelity", "count": 1}
    ]


def test_terminal_attempt_evidence_filters_stale_queue_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    blocked = _row(
        "blocked_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    blocked["primary"] = "indexed-struct-pointer-materialization"
    ready = _row(
        "ready_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    ready["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [blocked, ready])
    ledger = tmp_path / "attempt_ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": {
                    "blocked_fn": {
                        "function": "blocked_fn",
                        "move_on_recommended": True,
                        "move_on_reason": "repeated no-progress attempts",
                        "suspected_blocker": "no-safe-materialized-pointer",
                        "attempts": [
                            {
                                "index": 3,
                                "timestamp": 30.0,
                                "timestamp_utc": "2026-06-07T00:00:30+00:00",
                                "outcome": "blocked",
                                "classification": "indexed-struct-pointer",
                                "blocker": "no-safe-materialized-pointer",
                                "retained": False,
                                "note": "no source retained",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        attempt_ledger_path=ledger,
    )
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger))
    default_ledger_rows = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        attempt_ledger_path=ledger,
    )
    included = load_queue_rows(
        queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        attempt_ledger_path=ledger,
        include_terminal_attempts=True,
    )

    assert [row.function for row in rows] == ["ready_fn"]
    assert [row.function for row in default_ledger_rows] == ["ready_fn"]
    assert preview["counts"]["terminal_attempt_rows"] == 1
    assert preview["terminal_attempt_facets"]["terminal_attempt_blocker"] == [
        {"value": "no-safe-materialized-pointer", "count": 1}
    ]
    assert [row.function for row in included] == ["blocked_fn", "ready_fn"]
    assert included[0].terminal_attempt_status == "active"
    assert included[0].source_actionability == "tooling-blocked"
    assert select_harness(included[0]) is None
    for source_actionability in (
        "source-ceiling",
        "tooling-blocked",
        "manual-review",
    ):
        assert (
            select_harness(
                HarvestRequest(
                    function=f"{source_actionability}_fn",
                    work_bucket="indexed-struct-pointer",
                    match_percent=99.0,
                    file_path="melee/demo.c",
                    headline_tool="source-shape",
                    source_file=None,
                    primary="indexed-struct-pointer-materialization",
                    source_actionability=source_actionability,
                )
            )
            is None
        )
    assert (
        select_harness(
            HarvestRequest(
                function="diagnostic_terminal_fn",
                work_bucket="indexed-struct-pointer",
                match_percent=99.0,
                file_path="melee/demo.c",
                headline_tool="source-shape",
                source_file=None,
                primary="indexed-struct-pointer-materialization",
                source_actionability="diagnostic-only",
                terminal_attempt_status="active",
            )
        )
        is None
    )

    stale_queue = tmp_path / "queues" / "stale-indexed-struct-pointer.tsv"
    stale_row = _row(
        "stale_fn",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    stale_row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(stale_queue, [stale_row])
    stale_ledger = tmp_path / "stale_attempt_ledger.json"
    stale_ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": {
                    "stale_fn": {
                        "function": "stale_fn",
                        "move_on_recommended": True,
                        "suspected_blocker": "no-safe-materialized-pointer",
                        "attempts": [
                            {
                                "index": 1,
                                "timestamp": 1.0,
                                "outcome": "blocked",
                                "blocker": "no-safe-materialized-pointer",
                                "tool_sha256": "old-tool",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        harvest_module,
        "_harvest_tool_fingerprint",
        lambda work_bucket: "new-tool",
    )
    stale_rows = load_queue_rows(
        stale_queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        attempt_ledger_path=stale_ledger,
    )

    assert [row.function for row in stale_rows] == ["stale_fn"]
    assert stale_rows[0].terminal_attempt_status == "stale"
    assert stale_rows[0].source_actionability == "current-tools-indexed-pointer"
    assert select_harness(stale_rows[0]) == "indexed-struct-search"

    monkeypatch.setattr(
        harvest_module,
        "_harvest_tool_fingerprint",
        lambda work_bucket: None,
    )
    incomparable_rows = load_queue_rows(
        stale_queue,
        work_bucket="indexed-struct-pointer",
        repo_root=repo_root,
        attempt_ledger_path=stale_ledger,
        include_terminal_attempts=True,
    )

    assert incomparable_rows[0].terminal_attempt_status == "active"
    assert incomparable_rows[0].source_actionability == "tooling-blocked"
    assert select_harness(incomparable_rows[0]) is None


def test_data_symbol_no_name_magic_rebucket_ledgers_are_applied_to_queue_preview(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    exhausted = _name_magic_row("exhausted_fn", primary="data-symbol-relocation")
    ready = _name_magic_row("ready_fn", primary="data-symbol-relocation")
    _write_queue(queue, [exhausted, ready])
    ledger_dir = repo_root / "build" / "harvest"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "data-symbol-ledger.json").write_text(
        json.dumps(
            {
                "work_bucket": "data-symbol-relocation",
                "results": [
                    {
                        "function": "exhausted_fn",
                        "work_bucket": "data-symbol-relocation",
                        "source_actionability": (
                            "blocked-data-symbol-no-name-magic-candidate"
                        ),
                        "blocker": "no-name-magic-candidate",
                        "details": {
                            "source_actionability_rebucket": {
                                "from": "current-tools-data-symbol",
                                "to": (
                                    "blocked-data-symbol-no-name-magic-candidate"
                                ),
                                "remove_from": "current-tools-data-symbol",
                                "blocker": "no-name-magic-candidate",
                                "reason": (
                                    "no scored source candidate reached a true "
                                    "--no-name-magic match"
                                ),
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    current_rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )
    all_rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )

    assert [row.function for row in current_rows] == ["ready_fn"]
    assert [row.source_actionability for row in all_rows] == [
        "blocked-data-symbol-no-name-magic-candidate",
        "current-tools-data-symbol",
    ]
    assert select_harness(all_rows[0]) is None
    assert preview["counts"]["matching_rows"] == 1
    assert [row["function"] for row in preview["sample"]] == ["ready_fn"]
    assert preview["near_miss_facets"]["source_actionability"] == [
        {"value": "blocked-data-symbol-no-name-magic-candidate", "count": 1}
    ]


def test_data_symbol_no_name_magic_rebucket_fingerprint_mismatch_keeps_row_current(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    exhausted = _name_magic_row("exhausted_fn", primary="data-symbol-relocation")
    ready = _name_magic_row("ready_fn", primary="data-symbol-relocation")
    _write_queue(queue, [exhausted, ready])
    ledger_dir = repo_root / "build" / "harvest"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "data-symbol-ledger.json").write_text(
        json.dumps(
            {
                "work_bucket": "data-symbol-relocation",
                "results": [
                    {
                        "function": "exhausted_fn",
                        "work_bucket": "data-symbol-relocation",
                        "source_actionability": (
                            "blocked-data-symbol-no-name-magic-candidate"
                        ),
                        "blocker": "no-name-magic-candidate",
                        "details": {
                            "source_actionability_rebucket": {
                                "from": "current-tools-data-symbol",
                                "to": (
                                    "blocked-data-symbol-no-name-magic-candidate"
                                ),
                                "remove_from": "current-tools-data-symbol",
                                "blocker": "no-name-magic-candidate",
                                "reason": "stale name-magic evidence",
                                "fingerprint": {
                                    "source_sha256": "stale-source",
                                    "taxonomy_sha256": "stale-taxonomy",
                                },
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    current_rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )

    assert [row.function for row in current_rows] == ["exhausted_fn", "ready_fn"]
    assert [select_harness(row) for row in current_rows] == [
        "name-magic-source-declarations",
        "name-magic-source-declarations",
    ]
    assert preview["counts"]["matching_rows"] == 2


def test_data_symbol_no_name_magic_rebucket_matching_fingerprint_applies_to_preview(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    exhausted = _name_magic_row("exhausted_fn", primary="data-symbol-relocation")
    ready = _name_magic_row("ready_fn", primary="data-symbol-relocation")
    _write_queue(queue, [exhausted, ready])

    initial = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=_json_runner(
            {
                "blocker": "no-name-magic-candidate",
                "stop_condition": {
                    "kind": "unvalidated",
                    "blocker": "no-name-magic-candidate",
                    "reason": (
                        "no source candidate reached a true --no-name-magic match"
                    ),
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
        )[1],
        limit=1,
    )
    ledger_dir = repo_root / "build" / "harvest"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "data-symbol-ledger.json").write_text(
        json.dumps(initial),
        encoding="utf-8",
    )

    current_rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )

    assert initial["results"][0]["function"] == "exhausted_fn"
    assert (
        initial["results"][0]["source_actionability"]
        == "blocked-data-symbol-no-name-magic-candidate"
    )
    assert [row.function for row in current_rows] == ["ready_fn"]
    assert preview["counts"]["matching_rows"] == 1
    assert [row["function"] for row in preview["sample"]] == ["ready_fn"]


@pytest.mark.parametrize(
    "source_actionability",
    [
        "blocked-data-symbol-no-name-magic-candidate",
        "blocked-data-symbol-unsupported-source-site",
        "blocked-data-symbol-ambiguous-relocation-pair",
        "blocked-data-symbol-unsupported-reloc-kind",
        "blocked-data-symbol-raw-diff-no-supported-data-symbol-pair",
        "blocked-data-symbol-no-name-magic-validation-failed",
        "blocked-data-symbol-ambiguous-sdata2-value",
        "blocked-data-symbol-sdata2-pool-order-dependent",
    ],
)
def test_blocked_data_symbol_rows_do_not_select_name_magic_harness(
    source_actionability: str,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    row = _name_magic_row("blocked_fn", primary="data-symbol-or-relocation")
    row["source_actionability"] = source_actionability
    row["name_magic_blocker"] = source_actionability.removeprefix(
        "blocked-data-symbol-"
    )
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) is None
    assert harvest_module._normalize_layer_sequence(rows[0]) == []


def test_blocked_data_symbol_subqueue_rows_do_not_compose_name_magic(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.no-name-magic-candidate.tsv"
    row = _name_magic_row("blocked_fn", primary="data-symbol-or-relocation")
    row["source_actionability"] = "blocked-data-symbol-no-name-magic-candidate"
    row["name_magic_blocker"] = "no-name-magic-candidate"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation.no-name-magic-candidate",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) is None
    assert harvest_module._normalize_layer_sequence(rows[0]) == []


def test_blocked_data_symbol_target_map_can_explicitly_select_harness(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    row = _name_magic_row("blocked_fn", primary="data-symbol-or-relocation")
    row["source_actionability"] = "blocked-data-symbol-no-name-magic-candidate"
    row["name_magic_blocker"] = "no-name-magic-candidate"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="data-symbol-relocation",
        repo_root=repo_root,
        target_map={"blocked_fn": {"harness": "name-magic-source-declarations"}},
    )

    assert select_harness(rows[0]) == "name-magic-source-declarations"


def test_preview_harvest_queue_zero_match_reports_near_miss_facets(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    _write_queue(
        queue,
        [
            _structural_row(
                "current_structural",
                headline_tool="extract-opseq-xrefs",
                source_actionability="structural-rebuild",
            ),
            _structural_row(
                "backend_control_flow",
                headline_tool="control-flow-shape-search",
                source_actionability="backend-ceiling",
            ),
            _structural_row(
                "generator",
                headline_tool="manual-inspection",
                source_actionability="generator-gated",
            ),
        ],
    )

    preview = preview_harvest_queue(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={
                "source_actionability": ("structural-rebuild",),
                "headline_tool": ("control-flow-shape-search",),
            }
        ),
    )

    assert preview["counts"]["matching_rows"] == 0
    assert preview["sample"] == []
    assert preview["facet_source"] == "eligible_rows"
    assert preview["facets"]["source_actionability"] == [
        {"value": "backend-ceiling", "count": 1},
        {"value": "generator-gated", "count": 1},
        {"value": "structural-rebuild", "count": 1},
    ]
    assert preview["near_miss_facets"]["headline_tool"] == [
        {"value": "extract-opseq-xrefs", "count": 1}
    ]
    assert preview["near_miss_facets"]["source_actionability"] == [
        {"value": "backend-ceiling", "count": 1}
    ]


def test_preview_harvest_queue_rejects_taxonomy_artifacts_missing_run_status(
    tmp_path: Path,
) -> None:
    queue = write_minimal_taxonomy_queue(tmp_path / "function-taxonomy", None)

    with pytest.raises(ValueError, match="taxonomy inventory status is missing"):
        preview_harvest_queue(
            queue,
            work_bucket="signature-call-type",
            repo_root=REPO_ROOT,
        )


def test_preview_harvest_queue_rejects_incomplete_taxonomy_run(
    tmp_path: Path,
) -> None:
    for status in (
        {"status": "running", "started_at": "2026-06-05T12:00:00Z"},
        {
            "status": "failed",
            "started_at": "2026-06-05T12:00:00Z",
            "failed_at": "2026-06-05T12:01:00Z",
            "error": "boom",
        },
    ):
        taxonomy_root = tmp_path / status["status"] / "function-taxonomy"
        queue = write_minimal_taxonomy_queue(taxonomy_root, status)

        with pytest.raises(ValueError, match="taxonomy inventory has not completed"):
            preview_harvest_queue(
                queue,
                work_bucket="signature-call-type",
                repo_root=REPO_ROOT,
            )


def test_preview_harvest_queue_allows_completed_manifest_and_ad_hoc_queue(
    tmp_path: Path,
) -> None:
    completed_queue = write_minimal_taxonomy_queue(
        tmp_path / "completed" / "function-taxonomy",
        {
            "status": "completed",
            "started_at": "2026-06-05T12:00:00Z",
            "completed_at": "2026-06-05T12:02:00Z",
            "attempted_count": 1,
            "classified_count": 1,
            "error_count": 0,
        },
    )

    completed_preview = preview_harvest_queue(
        completed_queue,
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
    )
    assert completed_preview["counts"]["matching_rows"] == 1

    ad_hoc_dir = tmp_path / "ad-hoc-queues"
    ad_hoc_dir.mkdir()
    ad_hoc_queue = ad_hoc_dir / "signature-call-type.tsv"
    ad_hoc_queue.write_text(completed_queue.read_text(encoding="utf-8"), encoding="utf-8")

    ad_hoc_preview = preview_harvest_queue(
        ad_hoc_queue,
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
    )
    assert ad_hoc_preview["counts"]["matching_rows"] == 1


def test_preview_harvest_queue_allows_ad_hoc_queues_with_unrelated_status(
    tmp_path: Path,
) -> None:
    queue_dir = tmp_path / "queues"
    queue_dir.mkdir()
    queue = queue_dir / "signature-call-type.tsv"
    queue.write_text(
        "match_percent\tfunction\tprimary\tsubcategory\t"
        "source_actionability\theadline_tool\tfile_path\tnext_command\n"
        "99.0\tsig_fn\tsignature-type-mismatch\tcall-shape-or-prototype\t"
        "current-tools-signature-audit\tdebug-suggest-signatures\t"
        "melee/demo/demo.c\t"
        "melee-agent debug suggest signatures -f sig_fn "
        "--source-file src/melee/demo/demo.c --json\n",
        encoding="utf-8",
    )
    (tmp_path / "run-status.json").write_text(
        json.dumps({"status": "running"}),
        encoding="utf-8",
    )

    preview = preview_harvest_queue(
        queue,
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
    )

    assert preview["counts"]["matching_rows"] == 1


def test_run_harvest_filtered_limit_zero_keeps_filter_smoke_behavior(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )

    def fail_runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        raise AssertionError(f"limit-zero harvest must not run {args}")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        limit=0,
        runner=fail_runner,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools",)}
        ),
    )

    assert ledger["summary"]["total_rows"] == 0
    assert ledger["filters"] == {
        "where": {"source_actionability": ["current-tools"]}
    }


def test_run_harvest_filtered_zero_rows_raises_before_pcdump_and_ledger(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    ledger_path = tmp_path / "empty.json"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )

    def fail_lookup(_repo: Path, _unit: str):
        raise AssertionError("zero-match filtered harvest must not inspect pcdumps")

    def fail_runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        raise AssertionError(f"zero-match filtered harvest must not run {args}")

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fail_lookup)

    with pytest.raises(ValueError, match="filters matched zero rows"):
        run_harvest(
            "stack-local-layout",
            repo_root=repo_root,
            queue_path=queue,
            ledger_path=ledger_path,
            runner=fail_runner,
            filters=HarvestFilters(
                where={"source_actionability": ("source-probe",)}
            ),
        )

    assert not ledger_path.exists()


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


def test_run_harvest_prefetches_missing_current_tools_frame_transform_pcdumps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "melee/demo.c")
    other_source = repo_root / "src" / "melee" / "other.c"
    other_source.write_text("void other_fn(void) {}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                file_path="melee/demo.c",
                source_actionability="current-tools",
            ),
            _row(
                "demo_fn_2",
                file_path="melee/demo.c",
                source_actionability="current-tools",
            ),
            _row(
                "other_fn",
                file_path="melee/other.c",
                source_actionability="current-tools",
            ),
        ],
    )
    lookups: list[str] = []

    def fake_lookup(repo: Path, unit: str):
        lookups.append(unit)
        return None

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fake_lookup)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[:2] == ["debug", "dump"]:
            return HarnessProcessResult(args, 0, "", "")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[:3] == [
        ["debug", "dump", "setup"],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "demo.c"),
            "--function",
            "demo_fn",
        ],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "other.c"),
            "--function",
            "other_fn",
        ],
    ]
    assert [call[:3] for call in calls[3:]] == [
        ["debug", "mutate", "frame-transform-search"],
        ["debug", "mutate", "frame-transform-search"],
        ["debug", "mutate", "frame-transform-search"],
    ]
    assert lookups == ["melee/demo", "melee/other"]
    assert ledger["preflight"]["pcdump"]["required_units"] == [
        "melee/demo",
        "melee/other",
    ]
    assert ledger["preflight"]["pcdump"]["generated_units"] == [
        "melee/demo",
        "melee/other",
    ]


def test_lifetime_layout_source_probe_selects_harness(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                headline_tool="lifetime-layout",
                source_actionability="source-probe",
                frame_closability_tier="",
                next_command=(
                    "melee-agent debug mutate lifetime-layout -f demo_fn "
                    "--compile-probes --score-match-percent --json"
                ),
            )
        ],
    )

    rows = load_queue_rows(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "lifetime-layout"


def test_lifetime_layout_harvest_builds_scored_mutate_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                headline_tool="lifetime-layout",
                source_actionability="source-probe",
                frame_closability_tier="",
            )
        ],
    )
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
    entry = harvest_module.pcdump_cache.CacheEntry(
        path=repo_root / "build" / "mwcc_debug_cache" / "melee" / "demo.txt",
        source_path=repo_root / "src" / "melee" / "demo.c",
        fresh=True,
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: entry)

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[0] == [
        "debug",
        "mutate",
        "lifetime-layout",
        "-f",
        "demo_fn",
        "--source-file",
        str(repo_root / "src" / "melee/demo.c"),
        "--compile-probes",
        "--score-match-percent",
        "--json",
        "--max-probes",
        "8",
        "--timeout",
        "120",
    ]
    assert ledger["results"][0]["harness"] == "lifetime-layout"
    assert ledger["results"][0]["status"] == "validated"


def test_run_harvest_prefetches_lifetime_layout_source_probe_pcdumps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "melee/demo.c")
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                file_path="melee/demo.c",
                headline_tool="lifetime-layout",
                source_actionability="source-probe",
                frame_closability_tier="",
            ),
        ],
    )
    lookups: list[str] = []

    def fake_lookup(repo: Path, unit: str):
        lookups.append(unit)
        return None

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fake_lookup)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[:2] == ["debug", "dump"]:
            return HarnessProcessResult(args, 0, "", "")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[:2] == [
        ["debug", "dump", "setup"],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "demo.c"),
            "--function",
            "demo_fn",
        ],
    ]
    assert calls[2][:3] == ["debug", "mutate", "lifetime-layout"]
    assert lookups == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["generated_units"] == ["melee/demo"]


def test_run_harvest_prefetches_indexed_struct_compile_probe_pcdumps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "melee/demo.c")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        file_path="melee/demo.c",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    lookups: list[str] = []

    def fake_lookup(repo: Path, unit: str):
        lookups.append(unit)
        return None

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fake_lookup)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[:2] == ["debug", "dump"]:
            return HarnessProcessResult(args, 0, "", "")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[:2] == [
        ["debug", "dump", "setup"],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "demo.c"),
            "--function",
            "demo_fn",
        ],
    ]
    assert calls[2][:3] == ["debug", "mutate", "indexed-struct-search"]
    assert lookups == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["required_units"] == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["generated_units"] == ["melee/demo"]


def test_run_harvest_blocks_unsafe_indexed_pcdump_lane(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.local_safety import LocalWiboProcess

    repo_root = _repo_with_source(tmp_path, "sysdolphin/baselib/particle.c")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "hsd_80391AC8",
        file_path="sysdolphin/baselib/particle.c",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    unsafe = LocalWiboProcess(
        pid=80283,
        ppid=1,
        stat="UEs",
        elapsed="10:27",
        command=(
            "wibo mwcceppc_debug.exe "
            "-c src/sysdolphin/baselib/particle.c"
        ),
        source_rel="src/sysdolphin/baselib/particle.c",
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: None)
    monkeypatch.setattr(
        harvest_module.local_safety,
        "scan_local_wibo_processes",
        lambda: [unsafe],
    )
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls == []
    assert ledger["preflight"]["pcdump"]["unsafe_units"] == [
        "sysdolphin/baselib/particle"
    ]
    assert ledger["preflight"]["pcdump"]["unsafe_processes"][0]["pid"] == 80283
    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "unsafe-local-pcdump-lane"
    assert result["harness"] == "indexed-struct-search"
    assert "uninterruptible wibo" in result["reason"]


def test_run_harvest_marks_dump_local_unsafe_returncode_before_scoring(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "sysdolphin/baselib/particle.c")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "hsd_80391AC8",
        file_path="sysdolphin/baselib/particle.c",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: None)
    monkeypatch.setattr(
        harvest_module.local_safety,
        "scan_local_wibo_processes",
        lambda: [],
    )
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args == ["debug", "dump", "setup"]:
            return HarnessProcessResult(args, 0, "", "")
        if args[:3] == ["debug", "dump", "local"]:
            return HarnessProcessResult(
                args,
                125,
                "",
                (
                    "unsafe local pcdump lane for hsd_80391AC8: "
                    "existing uninterruptible wibo process"
                ),
            )
        raise AssertionError(f"candidate scoring should be skipped: {args}")

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert [call[:3] for call in calls] == [
        ["debug", "dump", "setup"],
        ["debug", "dump", "local"],
    ]
    assert ledger["preflight"]["pcdump"]["unsafe_units"] == [
        "sysdolphin/baselib/particle"
    ]
    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "unsafe-local-pcdump-lane"


def test_run_harvest_does_not_overblock_same_unit_without_pcdump_preflight(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.local_safety import LocalWiboProcess

    repo_root = _repo_with_source(tmp_path, "sysdolphin/baselib/particle.c")
    queue = tmp_path / "queues" / "inline-boundary.tsv"
    row = _row(
        "hsd_80391AC8",
        file_path="sysdolphin/baselib/particle.c",
        headline_tool="patterns-inlines",
        source_actionability="manual-inline-guidance",
        frame_closability_tier="",
    )
    row["primary"] = "missing-reference-call-current-inlined"
    _write_queue(queue, [row])
    unsafe = LocalWiboProcess(
        pid=80283,
        ppid=1,
        stat="UEs",
        elapsed="10:27",
        command=(
            "wibo mwcceppc_debug.exe "
            "-c src/sysdolphin/baselib/particle.c"
        ),
        source_rel="src/sysdolphin/baselib/particle.c",
    )
    monkeypatch.setattr(
        harvest_module.local_safety,
        "scan_local_wibo_processes",
        lambda: [unsafe],
    )

    ledger = run_harvest(
        "inline-boundary",
        repo_root=repo_root,
        queue_path=queue,
    )

    assert ledger["preflight"]["pcdump"]["enabled"] is False
    assert ledger["results"][0]["blocker"] == "unsupported-harness"


def test_indexed_struct_pcdump_setup_failure_stops_before_compile_probe_scoring(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "melee/demo.c")
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        file_path="melee/demo.c",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: None)

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        if args == ["debug", "dump", "setup"]:
            return HarnessProcessResult(args, 7, "", "missing mwcceppc_debug.exe")
        raise AssertionError(f"unexpected command after setup failure: {args}")

    with pytest.raises(ValueError, match="pcdump preflight setup failed"):
        run_harvest(
            "indexed-struct-pointer",
            repo_root=repo_root,
            queue_path=queue,
            runner=runner,
        )


def test_indexed_struct_preflight_runs_setup_when_cache_is_fresh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "melee/demo.c")
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    row = _row(
        "demo_fn",
        file_path="melee/demo.c",
        headline_tool="source-shape",
        source_actionability="current-tools-indexed-pointer",
        frame_closability_tier="",
    )
    row["primary"] = "indexed-struct-pointer-materialization"
    _write_queue(queue, [row])
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "indexed-struct-pointer",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[0] == ["debug", "dump", "setup"]
    assert all(call[:3] != ["debug", "dump", "local"] for call in calls)
    assert calls[1][:3] == ["debug", "mutate", "indexed-struct-search"]
    assert ledger["preflight"]["pcdump"]["fresh_units"] == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["setup_command"]["returncode"] == 0


def test_run_harvest_skips_pcdump_preflight_when_frame_transform_cache_is_fresh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )
    cache_path = repo_root / "build" / "mwcc_debug_cache" / "melee" / "demo.txt"
    entry = harvest_module.pcdump_cache.CacheEntry(
        path=cache_path,
        source_path=repo_root / "src" / "melee" / "demo.c",
        fresh=True,
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: entry)
    calls, runner = _json_runner({"variants": []})

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
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
    assert ledger["preflight"]["pcdump"]["fresh_units"] == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["generated_units"] == []


def test_run_harvest_refreshes_stale_frame_transform_pcdumps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )
    entry = harvest_module.pcdump_cache.CacheEntry(
        path=repo_root / "build" / "mwcc_debug_cache" / "melee" / "demo.txt",
        source_path=repo_root / "src" / "melee" / "demo.c",
        fresh=False,
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: entry)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[:2] == ["debug", "dump"]:
            return HarnessProcessResult(args, 0, "", "")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[:2] == [
        ["debug", "dump", "setup"],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "demo.c"),
            "--function",
            "demo_fn",
        ],
    ]
    assert ledger["preflight"]["pcdump"]["stale_units"] == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["generated_units"] == ["melee/demo"]


def test_run_harvest_pcdump_preflight_accepts_cache_written_before_dump_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )
    cache_path = repo_root / "build" / "mwcc_debug_cache" / "melee" / "demo.txt"
    lookups: list[str] = []

    def fake_lookup(repo: Path, unit: str):
        lookups.append(unit)
        if len(lookups) == 1:
            return None
        return harvest_module.pcdump_cache.CacheEntry(
            path=cache_path,
            source_path=repo_root / "src" / "melee" / "demo.c",
            fresh=True,
        )

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fake_lookup)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args == ["debug", "dump", "setup"]:
            return HarnessProcessResult(args, 0, "", "")
        if args[:3] == ["debug", "dump", "local"]:
            return HarnessProcessResult(args, 3, "wrote cache then failed", "wibo UE")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[-1][:3] == ["debug", "mutate", "frame-transform-search"]
    assert lookups == ["melee/demo", "melee/demo"]
    assert ledger["preflight"]["pcdump"]["generated_units"] == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["failed_units"] == []


def test_run_harvest_pcdump_preflight_records_dump_failure_and_continues(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: None)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args == ["debug", "dump", "setup"]:
            return HarnessProcessResult(args, 0, "", "")
        if args[:3] == ["debug", "dump", "local"]:
            return HarnessProcessResult(args, 3, "", "wibo stayed UE")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[-1][:3] == ["debug", "mutate", "frame-transform-search"]
    assert ledger["preflight"]["pcdump"]["generated_units"] == []
    assert ledger["preflight"]["pcdump"]["failed_units"] == ["melee/demo"]
    assert ledger["preflight"]["pcdump"]["dump_failures"][0]["unit"] == "melee/demo"
    assert "wibo stayed UE" in ledger["preflight"]["pcdump"]["dump_failures"][0]["stderr"]


def test_run_harvest_does_not_prefetch_non_current_tools_frame_transform_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn")])

    def fail_lookup(_repo: Path, _unit: str):
        raise AssertionError("pcdump cache should not be checked")

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fail_lookup)
    calls, runner = _json_runner({"variants": []})

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[0][:3] == ["debug", "mutate", "frame-transform-search"]
    assert ledger["preflight"]["pcdump"]["enabled"] is False


def test_run_harvest_prefetches_composed_current_tools_frame_transform_layer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                headline_tool="manual-inspection",
                source_actionability="current-tools",
                frame_closability_tier="current-tools-padstack",
            )
        ],
    )
    monkeypatch.setattr(
        harvest_module.pcdump_cache,
        "lookup",
        lambda _repo, _unit: None,
    )
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[:2] == ["debug", "dump"]:
            return HarnessProcessResult(args, 0, "", "")
        return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        target_map={
            "demo_fn": {
                "harnesses": [
                    {"harness": "name-magic-source-declarations"},
                    {"harness": "frame-transform-search"},
                ]
            }
        },
        compose=True,
        runner=runner,
    )

    assert calls[:2] == [
        ["debug", "dump", "setup"],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "demo.c"),
            "--function",
            "demo_fn",
        ],
    ]
    assert ledger["preflight"]["pcdump"]["generated_units"] == ["melee/demo"]


def test_run_harvest_pcdump_preflight_setup_failure_stops_before_row_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: None)

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        if args == ["debug", "dump", "setup"]:
            return HarnessProcessResult(args, 7, "", "setup failed")
        raise AssertionError(f"unexpected command after setup failure: {args}")

    with pytest.raises(ValueError, match="pcdump preflight setup failed"):
        run_harvest(
            "stack-local-layout",
            repo_root=repo_root,
            queue_path=queue,
            runner=runner,
        )


def test_run_harvest_pcdump_preflight_runner_exception_is_clean_value_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )
    monkeypatch.setattr(
        harvest_module.pcdump_cache,
        "lookup",
        lambda _repo, _unit: None,
    )

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        raise RuntimeError(f"could not run {args}")

    with pytest.raises(ValueError, match="pcdump preflight setup failed to run"):
        run_harvest(
            "stack-local-layout",
            repo_root=repo_root,
            queue_path=queue,
            runner=runner,
        )


def test_allocator_pcdump_triage_selects_harness(tmp_path: Path) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])

    rows = load_queue_rows(
        queue,
        work_bucket="register-allocator",
        repo_root=repo_root,
    )
    override_rows = load_queue_rows(
        queue,
        work_bucket="register-allocator",
        repo_root=repo_root,
        target_map={"demo_fn": {"harness": "coalesce-search", "target": "37=40"}},
    )
    non_allocator = HarvestRequest(
        function="demo_fn",
        work_bucket="stack-local-layout",
        match_percent=99.0,
        file_path="melee/demo.c",
        headline_tool="mwcc-debug",
        source_file=repo_root / "src" / "melee" / "demo.c",
        source_actionability="pcdump-proof-needed",
        next_command="melee-agent debug dump local src/melee/demo.c --function demo_fn",
    )

    assert select_harness(rows[0]) == "allocator-pcdump-triage"
    assert select_harness(override_rows[0]) == "coalesce-search"
    assert select_harness(non_allocator) is None


def test_allocator_pcdump_triage_builds_match_iter_first_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    calls, runner = _json_runner(_allocator_triage_payload())

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls == [
        [
            "debug",
            "target",
            "match-iter-first",
            "-f",
            "demo_fn",
            "--regs",
            "gpr-callee,gpr-volatile,r0",
            "--force-vector",
            "auto",
            "--json",
        ]
    ]
    assert ledger["results"][0]["harness"] == "allocator-pcdump-triage"


def test_run_harvest_prefetches_allocator_pcdump_triage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path, "melee/demo.c")
    other_source = repo_root / "src" / "melee" / "other.c"
    other_source.write_text("void other_fn(void) {}\n", encoding="utf-8")
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(
        queue,
        [
            _allocator_row("demo_fn", file_path="melee/demo.c"),
            _allocator_row("demo_fn_2", file_path="melee/demo.c"),
            _allocator_row("other_fn", file_path="melee/other.c"),
        ],
    )
    lookups: list[str] = []

    def fake_lookup(_repo: Path, unit: str):
        lookups.append(unit)
        return None

    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", fake_lookup)
    calls: list[list[str]] = []

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        calls.append(args)
        if args[:2] == ["debug", "dump"]:
            return HarnessProcessResult(args, 0, "", "")
        return HarnessProcessResult(args, 0, json.dumps(_allocator_triage_payload()), "")

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[:3] == [
        ["debug", "dump", "setup"],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "demo.c"),
            "--function",
            "demo_fn",
        ],
        [
            "debug",
            "dump",
            "local",
            str(repo_root / "src" / "melee" / "other.c"),
            "--function",
            "other_fn",
        ],
    ]
    assert calls[3:] == [
        [
            "debug",
            "target",
            "match-iter-first",
            "-f",
            function,
            "--regs",
            "gpr-callee,gpr-volatile,r0",
            "--force-vector",
            "auto",
            "--json",
        ]
        for function in ("demo_fn", "demo_fn_2", "other_fn")
    ]
    assert lookups == ["melee/demo", "melee/other"]
    assert ledger["preflight"]["pcdump"]["required_units"] == [
        "melee/demo",
        "melee/other",
    ]
    assert ledger["preflight"]["pcdump"]["generated_units"] == [
        "melee/demo",
        "melee/other",
    ]


def test_allocator_pcdump_triage_records_target_vector_blocker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload()
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "allocator-target-vector"
    assert result["candidate_path"] is None
    assert result["details"]["target_vector_actionability"] == payload[
        "target_vector_actionability"
    ]
    assert result["details"]["force_vector"] == "r26=r31"
    assert result["details"]["force_vector_runnable"] is True
    assert result["details"]["force_vector_recommended"] is True
    assert result["details"]["force_phys_csv"] == "r26,r31"
    assert result["details"]["force_vector_conflicts"] == []
    assert result["details"]["unit"] == "melee/demo"
    assert result["details"]["targets"] == [{"from": "r26", "to": "r31"}]
    assert result["details"]["results"] == [{"target": "r26=r31", "status": "ok"}]
    assert result["details"]["pcdump"] == str(
        harvest_module.pcdump_cache.cache_path(repo_root, "melee/demo")
    )
    assert "needs-move summary" in result["reason"]
    assert "needs-move next step" in result["reason"]


def test_allocator_pcdump_triage_records_force_vector_diagnostic_match(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload()
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=True)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "diagnostic_match"
    assert result["blocker"] == "allocator-force-vector-match"
    assert result["candidate_path"] is None
    assert result["details"]["force_vector_verify"] == payload["force_vector_verify"]
    assert result["details"]["force_vector_matched_probes"] == [
        {
            "label": "union",
            "ordinal": None,
            "status": "match",
            "entries": payload["force_vector_verify"]["union"]["entries"],
        }
    ]
    assert result["details"]["source_transform_hint"]["kind"] == (
        "allocator-force-vector-match"
    )
    assert result["details"]["source_transform_hint"]["matched_probe_labels"] == [
        "union"
    ]
    assert "force-vector union matched" in result["reason"]


def test_allocator_pcdump_triage_records_singleton_force_vector_diagnostic_match(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    singleton = {
        "label": "single[1]",
        "ordinal": 1,
        "entries": [
            {
                "raw": "class0:ig36:phys=r6",
                "kind": "force_phys",
                "class_id": 0,
                "ig_idx": 36,
                "phys": 6,
            }
        ],
        "returncode": 0,
        "match": True,
        "status": "match",
        "stdout_tail": "[diff] MATCH",
        "stderr_tail": "",
    }
    payload = _allocator_triage_payload()
    payload["force_vector_verify"] = _force_vector_verify_payload(
        union_match=False,
        probes=[singleton],
    )
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "diagnostic_match"
    assert result["blocker"] == "allocator-force-vector-match"
    assert result["details"]["force_vector_matched_probes"] == [
        {
            "label": "single[1]",
            "ordinal": 1,
            "status": "match",
            "entries": singleton["entries"],
        }
    ]
    assert result["details"]["source_transform_hint"]["matched_probe_labels"] == [
        "single[1]"
    ]


def test_allocator_pcdump_triage_records_force_vector_no_match_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload()
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "allocator-force-vector-no-match"
    assert result["details"]["force_vector_verify"] == payload["force_vector_verify"]
    assert result["details"]["force_vector_matched_probes"] == []
    assert "no force-vector probe matched" in result["reason"]


def test_allocator_force_vector_no_match_rebuckets_already_satisfied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(status="already-satisfied")
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "allocator-force-vector-no-match"
    assert result["source_actionability"] == "source-lifetime-callee-save-shape"
    assert ledger["summary"]["by_tier"] == {
        "source-lifetime-callee-save-shape": 1
    }
    rebucket = result["details"]["source_actionability_rebucket"]
    assert rebucket["fingerprint"].keys() >= {
        "source_sha256",
        "taxonomy_sha256",
        "row_tool_sha256",
        "tool_sha256",
    }
    assert {key: value for key, value in rebucket.items() if key != "fingerprint"} == {
        "from": "pcdump-proof-needed",
        "to": "source-lifetime-callee-save-shape",
        "remove_from": "pcdump-proof-needed",
        "blocker": "allocator-force-vector-no-match",
        "reason": (
            "force-vector probes did not match and target vector is already "
            "satisfied; pivot to source lifetime/callee-save shape"
        ),
    }


def test_allocator_force_vector_no_match_rebuckets_conflict(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(
        force_vector_conflicts=["r26 conflicts with requested vector"]
    )
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "allocator-force-vector-no-match"
    assert result["source_actionability"] == "allocator-target-conflict"
    rebucket = result["details"]["source_actionability_rebucket"]
    assert rebucket["fingerprint"].keys() >= {
        "source_sha256",
        "taxonomy_sha256",
        "row_tool_sha256",
        "tool_sha256",
    }
    assert {key: value for key, value in rebucket.items() if key != "fingerprint"} == {
        "from": "pcdump-proof-needed",
        "to": "allocator-target-conflict",
        "remove_from": "pcdump-proof-needed",
        "blocker": "allocator-force-vector-no-match",
        "reason": (
            "force-vector probes did not match and target-vector override "
            "conflicts or is not runnable"
        ),
    }


def test_allocator_force_vector_no_match_rebuckets_needs_move_target_vector(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload()
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["source_actionability"] == "allocator-target-vector"
    assert result["details"]["source_actionability_rebucket"]["to"] == (
        "allocator-target-vector"
    )


def test_allocator_force_vector_no_match_rebuckets_non_runnable_conflict(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(force_vector_runnable=False)
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["source_actionability"] == "allocator-target-conflict"
    assert result["details"]["source_actionability_rebucket"]["to"] == (
        "allocator-target-conflict"
    )


def test_allocator_force_vector_no_match_rebucket_requires_pcdump_proof_lane(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(
        queue,
        [_allocator_row("demo_fn", source_actionability="source-probe")],
    )
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(status="already-satisfied")
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["source_actionability"] == "source-probe"
    assert "source_actionability_rebucket" not in result["details"]


def test_allocator_force_vector_rebucket_fingerprint_filters_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("answered_fn"), _allocator_row("ready_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(status="already-satisfied")
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)

    initial = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=_json_runner(payload)[1],
        limit=1,
    )
    ledger_dir = repo_root / "build" / "harvest"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "register-allocator-ledger.json").write_text(
        json.dumps(initial),
        encoding="utf-8",
    )

    current_rows = load_queue_rows(
        queue,
        work_bucket="register-allocator",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("pcdump-proof-needed",)}
        ),
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="register-allocator",
        repo_root=repo_root,
        filters=HarvestFilters(
            where={"source_actionability": ("pcdump-proof-needed",)}
        ),
    )
    all_rows = load_queue_rows(
        queue,
        work_bucket="register-allocator",
        repo_root=repo_root,
    )

    assert initial["results"][0]["function"] == "answered_fn"
    assert initial["results"][0]["source_actionability"] == (
        "source-lifetime-callee-save-shape"
    )
    assert [row.function for row in current_rows] == ["ready_fn"]
    assert [row.source_actionability for row in all_rows] == [
        "source-lifetime-callee-save-shape",
        "pcdump-proof-needed",
    ]
    assert select_harness(all_rows[0]) is None
    assert select_harness(all_rows[1]) == "allocator-pcdump-triage"
    assert preview["counts"]["matching_rows"] == 1
    assert [row["function"] for row in preview["sample"]] == ["ready_fn"]


def test_allocator_pcdump_triage_records_force_vector_verify_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload()
    payload["force_vector_verify"] = _force_vector_verify_payload(union_match=False)
    payload["force_vector_verify"]["union"]["status"] = "failed"
    payload["force_vector_verify"]["union"]["returncode"] = 1
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "allocator-force-vector-verify-failed"
    assert result["details"]["force_vector_matched_probes"] == []
    assert "one or more probes failed" in result["reason"]


def test_allocator_pcdump_triage_records_source_lifetime_blocker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(
        status="already-satisfied",
        force_vector_recommended=False,
    )
    payload["variants"] = [
        {
            "status": "ok",
            "source_path": str(tmp_path / "candidate.c"),
            "final_match_percent": 100.0,
        }
    ]
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "source-lifetime-callee-save-shape"
    assert result["candidate_path"] is None


def test_allocator_pcdump_triage_uses_actionability_counts_without_targets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(force_vector_conflicts=["ig32 conflicts"])
    payload.pop("targets")
    payload["target_vector_actionability"]["target_count"] = 8
    payload["target_vector_actionability"]["runnable_target_count"] = 6
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "allocator-vector-not-runnable"
    assert result["details"]["force_vector_conflicts"] == ["ig32 conflicts"]
    assert "targets" not in result["details"]


@pytest.mark.parametrize(
    ("payload", "expected_blocker"),
    [
        (
            _allocator_triage_payload(status="current-unknown"),
            "allocator-current-unknown",
        ),
        (
            _allocator_triage_payload(
                status="current-unknown",
                force_vector_recommended=False,
            ),
            "allocator-current-unknown",
        ),
        (
            _allocator_triage_payload(
                status="already-satisfied",
                force_vector_conflicts=["already target but conflict metadata exists"],
            ),
            "source-lifetime-callee-save-shape",
        ),
        (
            _allocator_triage_payload(targets=[]),
            "allocator-no-targets",
        ),
        (
            _allocator_triage_payload(force_vector_runnable=False),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(force_vector_recommended=False),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(force_vector_recommended=None),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(force_vector_runnable=None),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(force_vector=""),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(
                status="no-runnable-targets",
                force_vector="",
                force_vector_runnable=False,
            ),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(
                status="future-status",
                force_vector_runnable=False,
            ),
            "allocator-vector-not-runnable",
        ),
        (
            _allocator_triage_payload(
                force_vector_conflicts=["r26 conflicts with requested vector"],
            ),
            "allocator-vector-not-runnable",
        ),
    ],
)
def test_allocator_pcdump_triage_records_narrow_blockers(
    monkeypatch,
    tmp_path: Path,
    payload: dict,
    expected_blocker: str,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == expected_blocker
    if payload.get("force_vector_conflicts"):
        assert result["details"]["force_vector_conflicts"] == payload[
            "force_vector_conflicts"
        ]


def test_allocator_pcdump_triage_missing_source_is_blocked(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn", file_path="melee/missing.c")])
    calls, runner = _json_runner(_allocator_triage_payload())

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert calls == []
    assert result["status"] == "blocked"
    assert result["blocker"] == "missing-source-file"
    assert result["harness"] == "allocator-pcdump-triage"


def test_allocator_pcdump_triage_unclassified_payload_is_blocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = {
        "target_vector_actionability": {"unexpected": "shape"},
        "unit": "melee/demo",
        "targets": [{"from": "r26", "to": "r31"}],
        "results": [{"status": "unknown"}],
        "warning": "future match-iter-first diagnostic",
        "target_vector": {"future": "metadata"},
    }
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "allocator-triage-unclassified"
    assert result["details"]["target_vector_actionability"] == {
        "unexpected": "shape"
    }
    assert result["details"]["payload"] == payload


def test_composed_allocator_pcdump_triage_translates_payload_before_candidates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload(status="already-satisfied")
    payload["variants"] = [
        {
            "status": "ok",
            "source_path": str(tmp_path / "candidate.c"),
            "final_match_percent": 100.0,
        }
    ]
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        target_map={"demo_fn": {"harnesses": ["allocator-pcdump-triage"]}},
        compose=True,
        runner=runner,
        match_checker=lambda function, *, cwd, timeout: _match_process(
            function,
            match=False,
            percent=99.0,
            primary="register-allocation",
        ),
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "source-lifetime-callee-save-shape"
    assert result["details"]["layers"][0]["harness"] == "allocator-pcdump-triage"
    assert (
        result["details"]["layers"][0]["blocker"]
        == "source-lifetime-callee-save-shape"
    )


def test_allocator_pcdump_triage_apply_does_not_attempt_source_application(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "register-allocator.tsv"
    _write_queue(queue, [_allocator_row("demo_fn")])
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    payload = _allocator_triage_payload()
    payload["variants"] = [
        {
            "status": "ok",
            "source_path": str(tmp_path / "candidate.c"),
            "final_match_percent": 100.0,
        }
    ]
    calls, runner = _json_runner(payload)

    def fail_validator(
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        raise AssertionError(f"diagnostic harness must not validate {function}")

    ledger = run_harvest(
        "register-allocator",
        repo_root=repo_root,
        queue_path=queue,
        apply=True,
        runner=runner,
        validator=fail_validator,
        match_checker=lambda function, *, cwd, timeout: _match_process(
            function,
            match=False,
            percent=99.0,
            primary="register-allocation",
        ),
    )

    result = ledger["results"][0]
    assert calls == [
        [
            "debug",
            "target",
            "match-iter-first",
            "-f",
            "demo_fn",
            "--regs",
            "gpr-callee,gpr-volatile,r0",
            "--force-vector",
            "auto",
            "--json",
        ]
    ]
    assert result["status"] == "blocked"
    assert result["blocker"] == "allocator-target-vector"
    assert result["applied"] is False
    assert result["candidate_path"] is None


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


def test_control_flow_structural_branch_selects_control_flow_search(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    row = _row(
        "demo_fn",
        headline_tool="manual-inspection",
        source_actionability="structural-rebuild",
        frame_closability_tier="",
    )
    row["primary"] = "structural-reconstruction"
    row["subcategory"] = "branch-or-control-flow-shape"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "control-flow-shape-search"


def test_structural_rebuild_alone_does_not_select_control_flow_search(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "known-small-pattern-candidate.tsv"
    row = _row(
        "demo_fn",
        headline_tool="mismatch-db",
        source_actionability="structural-rebuild",
        frame_closability_tier="",
    )
    row["primary"] = "known-small-pattern-candidate"
    row["subcategory"] = "operand-order"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="known-small-pattern-candidate",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) is None


def test_control_flow_explicit_harness_selects_control_flow_search(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    row = _row(
        "demo_fn",
        headline_tool="manual-inspection",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
        target_map={"demo_fn": {"harness": "control-flow-shape-search"}},
    )

    assert select_harness(rows[0]) == "control-flow-shape-search"


def test_control_flow_command_text_selects_control_flow_search(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    row = _row(
        "demo_fn",
        headline_tool="manual-inspection",
        source_actionability="",
        frame_closability_tier="",
        next_command="melee-agent debug mutate control-flow-shape-search -f demo_fn",
    )
    row["primary"] = "other-primary"
    _write_queue(queue, [row])

    rows = load_queue_rows(
        queue,
        work_bucket="structural-reconstruction",
        repo_root=repo_root,
    )

    assert select_harness(rows[0]) == "control-flow-shape-search"


def test_control_flow_harvest_builds_control_flow_search_command(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    row = _row(
        "demo_fn",
        headline_tool="control-flow-shape-search",
        source_actionability="structural-rebuild",
        frame_closability_tier="",
    )
    row["primary"] = "structural-reconstruction"
    row["subcategory"] = "branch-or-control-flow-shape"
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
        "structural-reconstruction",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    assert calls[0][:5] == [
        "debug",
        "mutate",
        "control-flow-shape-search",
        "-f",
        "demo_fn",
    ]
    assert "--score-match-percent" in calls[0]
    assert ledger["results"][0]["harness"] == "control-flow-shape-search"
    assert ledger["results"][0]["status"] == "validated"


def test_indexed_struct_harvest_builds_indexed_search_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
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

    assert calls[-1][:5] == [
        "debug",
        "mutate",
        "indexed-struct-search",
        "-f",
        "demo_fn",
    ]
    assert "--score-match-percent" in calls[-1]
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
    assert (
        result["source_actionability"]
        == "blocked-data-symbol-no-name-magic-candidate"
    )
    assert ledger["summary"]["by_tier"] == {
        "blocked-data-symbol-no-name-magic-candidate": 1
    }
    assert result["details"]["best_candidate"]["no_name_magic_match"] is False
    rebucket = result["details"]["source_actionability_rebucket"]
    assert rebucket["fingerprint"].keys() >= {"source_sha256", "taxonomy_sha256"}
    assert {key: value for key, value in rebucket.items() if key != "fingerprint"} == {
        "from": "current-tools-data-symbol",
        "to": "blocked-data-symbol-no-name-magic-candidate",
        "remove_from": "current-tools-data-symbol",
        "blocker": "no-name-magic-candidate",
        "reason": "no scored source candidate reached a true --no-name-magic match",
    }


def test_name_magic_rebucket_scans_past_best_candidate_without_source(
    tmp_path: Path,
) -> None:
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
                    "final_match_percent": 100.0,
                    "no_name_magic_match": False,
                },
                {
                    "status": "ok",
                    "source_retained": str(tmp_path / "lower-score.c"),
                    "final_match_percent": 99.5,
                    "no_name_magic_match": False,
                },
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
    assert (
        result["source_actionability"]
        == "blocked-data-symbol-no-name-magic-candidate"
    )
    assert "source_actionability_rebucket" in result["details"]


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
    assert result["source_actionability"] == "current-tools-data-symbol"
    assert "source_actionability_rebucket" not in result["details"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-name-magic-candidate",
                "reason": "candidate had no retained source",
            },
            "variants": [
                {
                    "status": "ok",
                    "final_match_percent": 100.0,
                    "no_name_magic_match": False,
                }
            ],
        },
        {
            "blocker": "section-anchor-source-fixable-residual",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "section-anchor-source-fixable-residual",
                "reason": "needs section anchor source fix",
            },
            "variants": [
                {
                    "status": "ok",
                    "source_retained": "candidate.c",
                    "final_match_percent": 100.0,
                    "no_name_magic_match": False,
                }
            ],
        },
    ],
)
def test_name_magic_rebucket_requires_source_emitting_no_name_magic_exhaustion(
    tmp_path: Path,
    payload: dict,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "data-symbol-relocation.tsv"
    _write_queue(queue, [_name_magic_row("demo_fn", primary="data-symbol-relocation")])
    _, runner = _json_runner(payload)

    ledger = run_harvest(
        "data-symbol-relocation",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["source_actionability"] == "current-tools-data-symbol"
    assert "source_actionability_rebucket" not in result["details"]


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
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
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
    mutate_calls = [call for call in calls if call[:2] == ["debug", "mutate"]]
    assert [call[2] for call in mutate_calls] == ["indexed-struct-search"]


def test_compose_apply_preserves_sub100_improvement_and_continues_to_match(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("int demo_fn(void) {\n    return 1;\n}\n", encoding="utf-8")
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
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
    mutate_calls = [call for call in calls if call[:2] == ["debug", "mutate"]]
    assert [call[2] for call in mutate_calls] == [
        "indexed-struct-search",
        "frame-transform-search",
    ]
    assert result["details"]["layers"][0]["details"]["layer_outcome"] == (
        "verified-improvement"
    )
    assert target.read_text(encoding="utf-8") == (
        "int demo_fn(void) {\n    return 3;\n}\n"
    )


def test_compose_indexed_malformed_source_candidate_rebuckets_top_level(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    queue = tmp_path / "queues" / "composite.tsv"
    candidate = tmp_path / "indexed-candidate.c"
    candidate.write_text("int sibling(void) { return 2; }\n", encoding="utf-8")
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
            "blocker": "no-indexed-struct-candidate",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-indexed-struct-candidate",
                "reason": "no indexed-struct candidate reached a true 100% match",
            },
            "variants": [
                {
                    "label": "indexed-struct-pointer-0",
                    "operator": "indexed-struct-pointer",
                    "status": "build-failed",
                    "source_retained": str(candidate),
                    "error": (
                        "function 'demo_fn' not found in pcdump; "
                        "did you mean sibling"
                    ),
                }
            ],
        }
    )

    ledger = run_harvest(
        "composite",
        repo_root=repo_root,
        queue_path=queue,
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
    assert result["status"] == "blocked"
    assert result["blocker"] == "malformed-source-candidate"
    assert result["source_actionability"] == "candidate-generation-fidelity"
    assert ledger["summary"]["by_tier"] == {"candidate-generation-fidelity": 1}
    assert result["details"]["source_actionability_rebucket"] == {
        "from": "current-tools-indexed-pointer",
        "to": "candidate-generation-fidelity",
        "remove_from": "current-tools-indexed-pointer",
        "blocker": "malformed-source-candidate",
        "reason": "candidate pcdump omitted the requested function",
    }
    layer = result["details"]["layers"][0]
    assert layer["source_actionability"] == "candidate-generation-fidelity"
    assert layer["details"]["malformed_source_candidate"]["source_path"] == str(candidate)
    assert (
        layer["details"]["malformed_source_candidate"]["error"]
        == "function 'demo_fn' not found in pcdump; did you mean sibling"
    )


def test_compose_name_magic_no_match_rebuckets_top_level(tmp_path: Path) -> None:
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
        match_checker=lambda function, *, cwd, timeout: _match_process(
            function,
            match=False,
            percent=99.0,
            primary="data-symbol-relocation",
        ),
        compose=True,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "no-name-magic-candidate"
    assert (
        result["source_actionability"]
        == "blocked-data-symbol-no-name-magic-candidate"
    )
    rebucket = result["details"]["source_actionability_rebucket"]
    assert rebucket["fingerprint"].keys() >= {"source_sha256", "taxonomy_sha256"}
    assert {key: value for key, value in rebucket.items() if key != "fingerprint"} == {
        "from": "current-tools-data-symbol",
        "to": "blocked-data-symbol-no-name-magic-candidate",
        "remove_from": "current-tools-data-symbol",
        "blocker": "no-name-magic-candidate",
        "reason": "no scored source candidate reached a true --no-name-magic match",
    }
    assert result["details"]["layers"][0]["details"][
        "source_actionability_rebucket"
    ] == result["details"]["source_actionability_rebucket"]
    assert ledger["summary"]["by_tier"] == {
        "blocked-data-symbol-no-name-magic-candidate": 1
    }


def test_compose_dry_run_restores_harness_source_mutation_when_ledger_write_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    _install_fresh_pcdump_cache(monkeypatch, repo_root)
    target = repo_root / "src" / "melee" / "demo.c"
    original = target.read_text(encoding="utf-8")
    mutated = "void demo_fn(void) { int leaked_mutation = 1; }\n"
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [_row("demo_fn", source_actionability="current-tools")],
    )

    def runner(args: list[str], *, cwd: Path, timeout: int) -> HarnessProcessResult:
        if args[:2] == ["debug", "mutate"]:
            target.write_text(mutated, encoding="utf-8")
            return HarnessProcessResult(args, 0, json.dumps({"variants": []}), "")
        return HarnessProcessResult(args, 0, "", "")

    def fail_write_ledger(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(harvest_module, "write_ledger", fail_write_ledger)

    with pytest.raises(OSError, match="No space left on device"):
        run_harvest(
            "stack-local-layout",
            repo_root=repo_root,
            queue_path=queue,
            runner=runner,
            match_checker=lambda function, *, cwd, timeout: _match_process(
                function,
                match=False,
                percent=90.0,
                primary="stack-layout",
            ),
            ledger_path=tmp_path / "ledger.json",
            compose=True,
        )

    assert target.read_text(encoding="utf-8") == original


def test_compose_apply_preserves_name_magic_sub100_source_and_header(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    header = repo_root / "src" / "melee/demo.h"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('#include "demo.h"\nint demo_fn(void) { return 1; }\n')
    header.write_text("#ifndef DEMO_H\n#define DEMO_H\n\n#endif\n")
    candidate = tmp_path / "name_magic.c"
    candidate_header = tmp_path / "name_magic.h"
    candidate.write_text('#include "demo.h"\nint demo_fn(void) { return 2; }\n')
    candidate_header.write_text(
        "#ifndef DEMO_H\n#define DEMO_H\n\n"
        "extern volatile f32 demo_804D0000;\n\n"
        "#endif\n"
    )
    queue = tmp_path / "queues" / "composite.tsv"
    row = _row(
        "demo_fn",
        headline_tool="source-shape",
        source_actionability="",
        frame_closability_tier="",
    )
    row["primary"] = "data-symbol-or-relocation"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-name-magic-candidate",
            },
            "variants": [
                {
                    "status": "ok",
                    "source_retained": str(candidate),
                    "header_retained": str(candidate_header),
                    "final_match_percent": 95.0,
                    "no_name_magic_match": False,
                }
            ],
        }
    )
    match_payloads = iter(
        [
            _match_process(
                "demo_fn",
                match=False,
                percent=90.0,
                primary="data-symbol-or-relocation",
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
        target_map={"demo_fn": {"harnesses": ["name-magic-source-declarations"]}},
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
    assert result["details"]["layers"][0]["status"] == "applied"
    assert target.read_text() == candidate.read_text()
    assert header.read_text() == candidate_header.read_text()


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
    assert ledger["results"][0]["details"] == {
        "candidate_count": 1,
        "scored_candidate_count": 1,
        "unscored_candidate_count": 0,
        "best_candidate": {
            "status": "ok",
            "final_match_percent": 99.9,
            "source_path": str(tmp_path / "candidate.c"),
            "score_percent": 99.9,
        },
    }


def test_frame_transform_no_validated_current_tools_rebuckets_padstack_diagnostic(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn", source_actionability="current-tools")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "label": "frame-reservation-pad-stack-16",
                    "operator": "frame-reservation-pad-stack",
                    "status": "ok",
                    "source_path": str(tmp_path / "candidate.c"),
                    "final_match_percent": 99.933334,
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

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "no-validated-candidate"
    assert result["source_actionability"] == "diagnostic-only"
    assert result["details"]["best_candidate"]["label"] == (
        "frame-reservation-pad-stack-16"
    )
    assert result["details"]["best_candidate"]["score_percent"] == 99.933334
    rebucket = result["details"]["source_actionability_rebucket"]
    assert rebucket["fingerprint"].keys() >= {
        "source_sha256",
        "taxonomy_sha256",
        "row_tool_sha256",
        "tool_sha256",
    }
    assert {key: value for key, value in rebucket.items() if key != "fingerprint"} == {
        "from": "current-tools",
        "to": "diagnostic-only",
        "remove_from": "current-tools",
        "blocker": "no-validated-candidate",
        "reason": (
            "frame-transform scored PAD_STACK diagnostic candidates but no "
            "validated 100% source"
        ),
    }


def test_frame_transform_no_validated_current_tools_rebuckets_source_probe(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn", source_actionability="current-tools")])
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "label": "block-scope-0",
                    "operator": "block-scope",
                    "status": "ok",
                    "source_path": str(tmp_path / "candidate.c"),
                    "final_match_percent": 42.03846,
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

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "no-validated-candidate"
    assert result["source_actionability"] == "source-probe"
    rebucket = result["details"]["source_actionability_rebucket"]
    assert rebucket["fingerprint"].keys() >= {
        "source_sha256",
        "taxonomy_sha256",
        "row_tool_sha256",
        "tool_sha256",
    }
    assert {key: value for key, value in rebucket.items() if key != "fingerprint"} == {
        "from": "current-tools",
        "to": "source-probe",
        "remove_from": "current-tools",
        "blocker": "no-validated-candidate",
        "reason": (
            "frame-transform scored source-shape candidates but no validated "
            "100% source"
        ),
    }


def test_frame_transform_no_validated_rebucket_fingerprint_filters_preview(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(
        queue,
        [
            _row("answered_fn", source_actionability="current-tools"),
            _row("ready_fn", source_actionability="current-tools"),
        ],
    )
    payload = {
        "variants": [
            {
                "label": "frame-reservation-pad-stack-8",
                "operator": "frame-reservation-pad-stack",
                "status": "ok",
                "source_path": str(tmp_path / "candidate.c"),
                "final_match_percent": 99.91549,
            }
        ]
    }

    initial = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=_json_runner(payload)[1],
        limit=1,
    )
    ledger_dir = repo_root / "build" / "harvest"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "stack-ledger.json").write_text(
        json.dumps(initial),
        encoding="utf-8",
    )

    current_rows = load_queue_rows(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
        filters=HarvestFilters(where={"source_actionability": ("current-tools",)}),
    )
    all_rows = load_queue_rows(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
    )
    preview = preview_harvest_queue(
        queue,
        work_bucket="stack-local-layout",
        repo_root=repo_root,
        filters=HarvestFilters(where={"source_actionability": ("current-tools",)}),
    )

    assert initial["results"][0]["function"] == "answered_fn"
    assert initial["results"][0]["source_actionability"] == "diagnostic-only"
    assert [row.function for row in current_rows] == ["ready_fn"]
    assert [row.source_actionability for row in all_rows] == [
        "diagnostic-only",
        "current-tools",
    ]
    assert select_harness(all_rows[0]) is None
    assert select_harness(all_rows[1]) == "frame-transform-search"
    assert preview["counts"]["matching_rows"] == 1
    assert [row["function"] for row in preview["sample"]] == ["ready_fn"]


@pytest.mark.parametrize(
    ("source_actionability", "variants"),
    [
        (
            "source-reachable-candidate",
            [
                {
                    "label": "frame-reservation-pad-stack-16",
                    "operator": "frame-reservation-pad-stack",
                    "status": "ok",
                    "source_path": "candidate.c",
                    "final_match_percent": 99.9,
                }
            ],
        ),
        (
            "current-tools",
            [
                {
                    "label": "frame-reservation-pad-stack-16",
                    "operator": "frame-reservation-pad-stack",
                    "status": "build-failed",
                }
            ],
        ),
    ],
)
def test_frame_transform_no_validated_rebucket_requires_current_tools_scored_row(
    tmp_path: Path,
    source_actionability: str,
    variants: list[dict],
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    _write_queue(queue, [_row("demo_fn", source_actionability=source_actionability)])
    _, runner = _json_runner({"variants": variants})

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "no_match"
    assert result["blocker"] == "no-validated-candidate"
    assert result["source_actionability"] == source_actionability
    assert "source_actionability_rebucket" not in result["details"]


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


def test_harvest_classifies_indexed_candidate_that_omits_target_from_pcdump(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "indexed-struct-pointer.tsv"
    candidate = tmp_path / "indexed-candidate.c"
    candidate.write_text("int sibling(void) { return 2; }\n", encoding="utf-8")
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
            "blocker": "no-indexed-struct-candidate",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-indexed-struct-candidate",
                "reason": "no indexed-struct candidate reached a true 100% match",
            },
            "variants": [
                {
                    "label": "indexed-struct-pointer-0",
                    "operator": "indexed-struct-pointer",
                    "status": "build-failed",
                    "source_retained": str(candidate),
                    "error": (
                        "function 'demo_fn' not found in pcdump; "
                        "did you mean sibling"
                    ),
                }
            ],
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
    assert result["blocker"] == "malformed-source-candidate"
    assert result["reason"] == "generated source candidate did not preserve the requested function"
    assert result["source_actionability"] == "candidate-generation-fidelity"
    assert result["details"]["source_actionability_rebucket"] == {
        "from": "current-tools-indexed-pointer",
        "to": "candidate-generation-fidelity",
        "remove_from": "current-tools-indexed-pointer",
        "blocker": "malformed-source-candidate",
        "reason": "candidate pcdump omitted the requested function",
    }
    assert result["details"]["malformed_source_candidate"]["source_path"] == str(candidate)
    assert (
        result["details"]["malformed_source_candidate"]["error"]
        == "function 'demo_fn' not found in pcdump; did you mean sibling"
    )
    assert ledger["summary"]["by_tier"] == {"candidate-generation-fidelity": 1}


def test_harvest_classifies_lifetime_malformed_source_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "stack-local-layout.tsv"
    candidate = tmp_path / "lifetime-candidate.c"
    candidate.write_text("int sibling(void) { return 2; }\n", encoding="utf-8")
    _write_queue(
        queue,
        [
            _row(
                "demo_fn",
                headline_tool="lifetime-layout",
                source_actionability="source-probe",
                frame_closability_tier="",
            )
        ],
    )
    entry = harvest_module.pcdump_cache.CacheEntry(
        path=repo_root / "build" / "mwcc_debug_cache" / "melee" / "demo.txt",
        source_path=repo_root / "src" / "melee" / "demo.c",
        fresh=True,
    )
    monkeypatch.setattr(harvest_module.pcdump_cache, "lookup", lambda _repo, _unit: entry)
    _, runner = _json_runner(
        {
            "variants": [
                {
                    "label": "temp-introduction-0",
                    "operator": "temp-introduction",
                    "status": "malformed-source",
                    "source_retained": str(candidate),
                    "error": (
                        "function 'demo_fn' not found in pcdump; "
                        "compiled probe pcdump omitted the target function"
                    ),
                }
            ],
        }
    )

    ledger = run_harvest(
        "stack-local-layout",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "malformed-source-candidate"
    assert result["source_actionability"] == "candidate-generation-fidelity"
    assert result["details"]["source_actionability_rebucket"] == {
        "from": "source-probe",
        "to": "candidate-generation-fidelity",
        "remove_from": "source-probe",
        "blocker": "malformed-source-candidate",
        "reason": "candidate pcdump omitted the requested function",
    }
    assert result["details"]["malformed_source_candidate"]["source_path"] == str(candidate)
    assert ledger["summary"]["by_tier"] == {"candidate-generation-fidelity": 1}


def test_harvest_propagates_control_flow_search_stable_blocker(
    tmp_path: Path,
) -> None:
    repo_root = _repo_with_source(tmp_path)
    queue = tmp_path / "queues" / "structural-reconstruction.tsv"
    row = _row(
        "demo_fn",
        headline_tool="control-flow-shape-search",
        source_actionability="structural-rebuild",
        frame_closability_tier="",
    )
    row["primary"] = "structural-reconstruction"
    row["subcategory"] = "branch-or-control-flow-shape"
    _write_queue(queue, [row])
    _, runner = _json_runner(
        {
            "blocker": "no-control-flow-shape-probes",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "no-control-flow-shape-probes",
                "reason": "no safe control-flow source transform matched",
            },
            "variants": [],
        }
    )

    ledger = run_harvest(
        "structural-reconstruction",
        repo_root=repo_root,
        queue_path=queue,
        runner=runner,
    )

    result = ledger["results"][0]
    assert result["status"] == "blocked"
    assert result["blocker"] == "no-control-flow-shape-probes"
    assert result["reason"] == "no safe control-flow source transform matched"


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


def test_write_ledger_records_harvest_filters(tmp_path: Path) -> None:
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
        filters=HarvestFilters(
            where={"headline_tool": ("control-flow-shape-search",)},
            exclude_source_actionability=("backend-ceiling",),
        ),
        results=[],
    )

    assert ledger["filters"] == {
        "exclude_source_actionability": ["backend-ceiling"],
        "where": {"headline_tool": ["control-flow-shape-search"]},
    }
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["filters"] == (
        ledger["filters"]
    )


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


def test_name_magic_apply_replaces_source_and_header_candidate(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    header = repo_root / "src" / "melee/demo.h"
    target.parent.mkdir(parents=True)
    target.write_text('#include "demo.h"\nint demo_fn(void) { return 1; }\n')
    header.write_text("#ifndef DEMO_H\n#define DEMO_H\n\n#endif\n")
    candidate = tmp_path / "candidate.c"
    candidate_header = tmp_path / "candidate.h"
    candidate.write_text('#include "demo.h"\nint demo_fn(void) { return 2; }\n')
    candidate_header.write_text(
        "#ifndef DEMO_H\n#define DEMO_H\n\n"
        "extern volatile f32 demo_804D0000;\n\n"
        "#endif\n"
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
                    "header_retained": str(candidate_header),
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
    assert target.read_text() == candidate.read_text()
    assert header.read_text() == candidate_header.read_text()


def test_name_magic_apply_rolls_back_source_and_header_on_validation_fail(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "melee/demo.c"
    header = repo_root / "src" / "melee/demo.h"
    target.parent.mkdir(parents=True)
    original_source = '#include "demo.h"\nint demo_fn(void) { return 1; }\n'
    original_header = "#ifndef DEMO_H\n#define DEMO_H\n\n#endif\n"
    target.write_text(original_source)
    header.write_text(original_header)
    candidate = tmp_path / "candidate.c"
    candidate_header = tmp_path / "candidate.h"
    candidate.write_text('#include "demo.h"\nint demo_fn(void) { return 2; }\n')
    candidate_header.write_text(
        "#ifndef DEMO_H\n#define DEMO_H\n\n"
        "extern volatile f32 demo_804D0000;\n\n"
        "#endif\n"
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
                    "header_retained": str(candidate_header),
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
    assert target.read_text() == original_source
    assert header.read_text() == original_header


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
