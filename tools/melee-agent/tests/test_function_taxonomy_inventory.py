from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


def write_report(path: Path) -> None:
    report = {
        "units": [
            {
                "name": "main/melee/demo/demo",
                "metadata": {
                    "source_path": "src/melee/demo/demo.c",
                    "complete": False,
                },
                "functions": [
                    {
                        "name": "matched_fn",
                        "size": "12",
                        "fuzzy_match_percent": 100.0,
                        "metadata": {"virtual_address": "2147483648"},
                    },
                    {
                        "name": "stack_fn",
                        "size": "384",
                        "fuzzy_match_percent": 99.75,
                        "metadata": {"virtual_address": "2147483660"},
                    },
                    {
                        "name": "small_fn",
                        "size": "180",
                        "fuzzy_match_percent": 99.5,
                        "metadata": {"virtual_address": "2147484044"},
                    },
                    {
                        "name": "frame_fn",
                        "size": "420",
                        "fuzzy_match_percent": 99.25,
                        "metadata": {"virtual_address": "2147484100"},
                    },
                    {
                        "name": "broken_fn",
                        "size": "96",
                        "fuzzy_match_percent": 98.0,
                        "metadata": {"virtual_address": "2147484224"},
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(report), encoding="utf-8")


def fake_checkdiff(function: str):
    payloads = {
        "stack_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-slot-layout",
                "reasons": [
                    "opcode sequence matches; differences are operands, registers, labels, or offsets",
                    "2 differing paired lines reference stack slots",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 2},
            "reference_lines": 20,
            "current_lines": 20,
        },
        "small_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "operand-register-or-offset",
                "reasons": [
                    "opcode sequence matches; differences are operands, registers, labels, or offsets",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
            "reference_lines": 8,
            "current_lines": 8,
        },
        "frame_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-layout",
                "reasons": [
                    "frame reservation gap is too large; source-actionable transform unavailable",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
            "reference_lines": 32,
            "current_lines": 32,
        },
    }
    if function == "broken_fn":
        return 1, "", "error: could not find broken_fn in compiled object"
    return 1, json.dumps(payloads[function]), "checkdiff stderr"


def fake_decl_order_evaluator(candidate, _record):
    if candidate.function == "frame_fn":
        raise AssertionError("frame-size residuals must not run decl-order probes")
    return {
        "evaluated_status": "evaluated",
        "candidate_count": 3,
        "evaluated_candidate_count": 3,
        "skipped_count": 0,
        "best_decl_delta": 0.125,
        "best_ordering": "swap a <-> b",
        "baseline_pct": candidate.match_percent,
        "best_pct": candidate.match_percent + 0.125,
        "scope": candidate.function,
        "selected_scope_reason": "function-top",
    }


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_generate_inventory_classifies_report_functions_and_writes_outputs(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=fake_checkdiff,
        decl_order_evaluator=fake_decl_order_evaluator,
        frame_report_runner=None,
        workers=1,
    )

    assert result.report_non100_count == 4
    assert result.classified_count == 3
    assert result.error_count == 1

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert [row["function"] for row in records] == ["stack_fn", "small_fn", "frame_fn"]
    assert records[0]["file_path"] == "melee/demo/demo.c"
    assert records[0]["address"] == "0x8000000c"
    assert records[0]["match_tier"] == ">=99%"
    assert records[0]["work_bucket"] == "stack-local-layout"
    assert records[0]["subcategory"] == "same-frame-stack-slot-placement"
    assert records[0]["frame_cause"] == "stack-object-offset-shift"
    assert records[0]["frame_closability_tier"] == "reorder-gated-362"
    assert records[0]["source_actionability"] == "generator-gated"
    assert records[0]["headline_tool"] == "lifetime-layout"
    assert records[0]["decl_order_summary"]["best_decl_delta"] == 0.125
    assert records[0]["decl_order_summary"]["best_ordering"] == "swap a <-> b"
    assert records[0]["decl_order_best_delta"] == 0.125
    assert records[0]["decl_order_best_ordering"] == "swap a <-> b"
    assert records[0]["decl_order_evaluated_status"] == "evaluated"
    assert records[0]["decl_order_candidate_count"] == 3
    assert records[1]["known_small_pattern_candidate"] is True
    assert records[1]["work_bucket"] == "known-small-pattern-candidate"
    assert records[2]["work_bucket"] == "stack-local-layout"
    assert records[2]["subcategory"] == "frame-too-large"
    assert records[2]["frame_cause"] == "frame-too-large"
    assert records[2]["frame_closability_tier"] == "gen-gated-366"
    assert records[2]["source_actionability"] == "generator-gated"
    assert records[2]["headline_tool"] == "frame-transform-search"
    assert "#366" in records[2]["actionability_reason"]
    assert "decl_order_summary" not in records[2]
    assert "debug mutate frame-transform-search -f frame_fn" in records[2]["next_command"]

    errors = read_jsonl(output / "checkdiff-errors.jsonl")
    assert errors[0]["function"] == "broken_fn"
    assert "could not find broken_fn" in errors[0]["message"]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    assert (
        "match_percent\tfunction\tprimary\tsubcategory\t"
        "frame_cause\tframe_verdict\tframe_closability_tier\t"
        "frame_attribution_status\tframe_source_object_symbol\t"
        "source_actionability\theadline_tool\tactionability_reason\t"
        "decl_order_best_delta\tdecl_order_best_ordering\t"
        "decl_order_evaluated_status\tdecl_order_candidate_count\t"
        "file_path\tframe_next_command\tnext_command"
    ) in stack_queue
    assert (
        "99.75000\tstack_fn\tstack-slot-layout\tsame-frame-stack-slot-placement\t"
        "stack-object-offset-shift\tsource-reachable-candidate\treorder-gated-362\t"
        "checkdiff-only\t\tgenerator-gated\tlifetime-layout\t"
    ) in stack_queue
    assert "\t0.12500\tswap a <-> b\tevaluated\t3" in stack_queue
    assert (
        "99.25000\tframe_fn\tstack-layout\tframe-too-large\t"
        "frame-too-large\tunresolved-source-attribution\tgen-gated-366\t"
        "checkdiff-only\t\tgenerator-gated\tframe-transform-search\t"
    ) in stack_queue

    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "| Report non-100% | 4 |" in summary
    assert "| stack-local-layout | 2 |" in summary
    assert "| known-small-pattern-candidate | 1 |" in summary


def test_generate_inventory_honors_limit_before_running_checkdiff(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    seen: list[str] = []

    def runner(function: str):
        seen.append(function)
        return fake_checkdiff(function)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=1,
    )

    assert result.report_non100_count == 4
    assert result.attempted_count == 1
    assert seen == ["stack_fn"]


def test_generate_inventory_attaches_stack_frame_closability_fields(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/frame_demo",
                        "metadata": {
                            "source_path": "src/melee/demo/frame_demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "pure_frame_fn",
                                "size": "160",
                                "fuzzy_match_percent": 99.8,
                                "metadata": {"virtual_address": "2147485000"},
                            },
                            {
                                "name": "same_slot_fn",
                                "size": "168",
                                "fuzzy_match_percent": 99.7,
                                "metadata": {"virtual_address": "2147485100"},
                            },
                            {
                                "name": "low_spill_fn",
                                "size": "172",
                                "fuzzy_match_percent": 99.6,
                                "metadata": {"virtual_address": "2147485200"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str):
        payloads = {
            "pure_frame_fn": {
                "function": function,
                "classification": {
                    "primary": "stack-layout",
                    "stack_frame_delta": {"missing_stack_bytes": 16},
                    "reasons": ["frame reservation gap is too small"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            },
            "same_slot_fn": {
                "function": function,
                "classification": {
                    "primary": "stack-slot-layout",
                    "stack_slot_localizer": {"deltas": [4]},
                    "reasons": ["2 differing paired lines reference stack slots"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            },
            "low_spill_fn": {
                "function": function,
                "classification": {
                    "primary": "stack-slot-layout",
                    "stack_slot_localizer": {
                        "deltas": [12],
                        "reserved_low_spill_region": {
                            "kind": "reserved-unused-low-spill-region",
                            "closability_tier": "ceiling",
                        },
                    },
                    "reasons": ["reserved-but-unused low spill region candidate"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            },
        }
        return 1, json.dumps(payloads[function]), ""

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
    )

    assert result.classified_count == 3
    records = {row["function"]: row for row in read_jsonl(output / "taxonomy.records.jsonl")}

    pure = records["pure_frame_fn"]
    assert pure["frame_cause"] == "pure-reservation"
    assert pure["frame_closability_tier"] == "current-tools-padstack"
    assert pure["frame_verdict"] == "source-reachable-candidate"
    assert pure["frame_attribution_status"] == "checkdiff-only"
    assert pure["next_command"] == pure["frame_next_command"]
    assert "frame-transform-search" in pure["next_command"]
    assert pure["source_actionability"] == "current-tools"

    same_slot = records["same_slot_fn"]
    assert same_slot["frame_cause"] == "stack-object-offset-shift"
    assert same_slot["frame_closability_tier"] == "reorder-gated-362"
    assert same_slot["source_actionability"] == "generator-gated"

    low_spill = records["low_spill_fn"]
    assert low_spill["frame_cause"] == "reserved-unused-low-spill-region"
    assert low_spill["frame_closability_tier"] == "ceiling"
    assert low_spill["frame_raw_cause"] == "reserved-unused-low-spill-region"
    assert low_spill["source_actionability"] == "ceiling"

    csv_text = (output / "taxonomy.records.csv").read_text(encoding="utf-8")
    assert "frame_closability_tier" in csv_text.splitlines()[0]
    assert "frame_source_object_symbol" in csv_text.splitlines()[0]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    header = stack_queue.splitlines()[0]
    assert "frame_cause" in header
    assert "frame_verdict" in header
    assert "frame_closability_tier" in header
    assert "frame_next_command" in header


def test_generate_inventory_uses_frame_report_source_attribution(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/attributed",
                        "metadata": {
                            "source_path": "src/melee/demo/attributed.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "attributed_fn",
                                "size": "160",
                                "fuzzy_match_percent": 99.8,
                                "metadata": {"virtual_address": "2147486000"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "classification": {
                    "primary": "stack-layout",
                    "reasons": ["frame reservation gap needs attribution"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    def frame_report_runner(candidate):
        assert candidate.function == "attributed_fn"
        return {
            "function": "attributed_fn",
            "frame_first_divergence": {
                "status": "diverged",
                "cause_hypothesis": {
                    "kind": "lifetime-or-ordering-shift",
                    "source_object_symbol": "local_temp",
                },
                "source_attribution": {
                    "status": "source-object-attributed",
                    "primary_source_object": {
                        "symbol": "local_temp",
                        "current_offset": 24,
                        "expected_offset": 28,
                    },
                },
                "verdict": {
                    "status": "source-reachable-candidate",
                    "source_object_symbol": "local_temp",
                },
            },
        }

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=frame_report_runner,
        workers=1,
    )

    assert result.classified_count == 1
    [record] = read_jsonl(output / "taxonomy.records.jsonl")
    assert record["frame_cause"] == "lifetime-or-ordering-shift"
    assert record["frame_raw_cause"] == "lifetime-or-ordering-shift"
    assert record["frame_verdict"] == "source-reachable-candidate"
    assert record["frame_attribution_status"] == "source-object-attributed"
    assert record["frame_source_object_symbol"] == "local_temp"
    assert record["frame_source_object"]["current_offset"] == 24
    assert record["frame_closability_tier"] == "gen-gated-366"


def test_summarize_decl_order_payload_records_best_delta_and_ordering() -> None:
    from tools.function_taxonomy_inventory import summarize_decl_order_payload

    summary = summarize_decl_order_payload(
        {
            "baseline_pct": 99.1,
            "best_pct": 99.3,
            "scope": "demo_fn",
            "rounds": [
                {
                    "results": [
                        {"label": "swap a <-> b", "match_pct": 99.2, "delta": 0.1},
                        {"label": "swap b <-> c", "match_pct": 99.3, "delta": 0.2},
                    ]
                }
            ],
        }
    )

    assert summary["evaluated_status"] == "evaluated"
    assert summary["candidate_count"] == 2
    assert summary["evaluated_candidate_count"] == 2
    assert summary["best_decl_delta"] == 0.2
    assert summary["best_ordering"] == "swap b <-> c"


def test_summarize_decl_order_payload_records_dependency_stop_condition() -> None:
    from tools.function_taxonomy_inventory import summarize_decl_order_payload

    summary = summarize_decl_order_payload(
        {
            "rounds": [
                {
                    "results": [
                        {
                            "label": "swap ip <-> attr",
                            "match_pct": None,
                            "delta": None,
                            "skipped": True,
                            "skip_reason": "attr depends on ip",
                        }
                    ]
                }
            ],
        }
    )

    assert summary["evaluated_status"] == "no-freedom-init-dependency"
    assert summary["candidate_count"] == 1
    assert summary["evaluated_candidate_count"] == 0
    assert summary["skipped_count"] == 1
    assert summary["best_decl_delta"] is None
    assert summary["best_ordering"] == ""
