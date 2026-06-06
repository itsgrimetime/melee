from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest


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
                        "name": "same_frame_fn",
                        "size": "420",
                        "fuzzy_match_percent": 99.125,
                        "metadata": {"virtual_address": "2147484112"},
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
                "stack_slot_localizer": {
                    "frame_size": 64,
                    "mismatch_count": 2,
                    "deltas": [4],
                },
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
        "same_frame_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-layout",
                "stack_frame_delta": {
                    "expected_frame_size": 64,
                    "current_frame_size": 64,
                    "missing_stack_bytes": 0,
                },
                "reasons": [
                    "frame reservation gap is too large; stale checkdiff-only reason",
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

    assert result.report_non100_count == 5
    assert result.classified_count == 4
    assert result.error_count == 1

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert [row["function"] for row in records] == [
        "stack_fn",
        "small_fn",
        "frame_fn",
        "same_frame_fn",
    ]
    assert records[0]["file_path"] == "melee/demo/demo.c"
    assert records[0]["address"] == "0x8000000c"
    assert records[0]["match_tier"] == ">=99%"
    assert records[0]["work_bucket"] == "stack-local-layout"
    assert records[0]["subcategory"] == "same-frame-stack-slot-placement"
    assert records[0]["frame_cause"] == "stack-object-offset-shift"
    assert records[0]["frame_closability_tier"] == "reorder-gated-362"
    assert records[0]["frame_match_relevance"] == "match-neutral"
    assert "same-frame stack-slot" in records[0]["frame_match_relevance_reason"]
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
    assert records[1]["source_actionability"] == "manual-small-pattern"
    assert records[1]["headline_tool"] == "mismatch-db"
    assert "no source-emitting harvest harness" in records[1]["actionability_reason"]
    assert records[2]["work_bucket"] == "stack-local-layout"
    assert records[2]["subcategory"] == "frame-too-large"
    assert records[2]["frame_cause"] == "frame-too-large"
    assert records[2]["frame_closability_tier"] == "gen-gated-366"
    assert records[2]["source_actionability"] == "generator-gated"
    assert records[2]["headline_tool"] == "frame-transform-search"
    assert "#366" in records[2]["actionability_reason"]
    assert "decl_order_summary" not in records[2]
    assert "debug mutate frame-transform-search -f frame_fn" in records[2]["next_command"]
    assert records[3]["work_bucket"] == "stack-local-layout"
    assert records[3]["subcategory"] == "same-frame-stack-slot-placement"
    assert records[3]["frame_cause"] == "stack-object-offset-shift"
    assert records[3]["frame_closability_tier"] == "reorder-gated-362"
    assert records[3]["headline_tool"] == "lifetime-layout"
    assert "lifetime-layout -f same_frame_fn" in records[3]["next_command"]

    errors = read_jsonl(output / "checkdiff-errors.jsonl")
    assert errors[0]["function"] == "broken_fn"
    assert "could not find broken_fn" in errors[0]["message"]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    assert (
        "match_percent\tfunction\tprimary\tsubcategory\t"
        "offset_discrepancy_count\toffset_discrepancy_bases\t"
        "offset_discrepancy_disps\toffset_discrepancy_opcodes\t"
        "frame_cause\tframe_verdict\tframe_closability_tier\t"
        "frame_match_relevance\tframe_match_relevance_reason\t"
        "frame_attribution_status\tframe_source_object_symbol\t"
        "cast_audit_status\tcast_medium_plus_count\t"
        "source_actionability\theadline_tool\tactionability_reason\t"
        "decl_order_best_delta\tdecl_order_best_ordering\t"
        "decl_order_evaluated_status\tdecl_order_candidate_count\t"
        "file_path\tframe_next_command\tnext_command"
    ) in stack_queue
    assert (
        "99.75000\tstack_fn\tstack-slot-layout\tsame-frame-stack-slot-placement\t"
        "\t\t\t\t"
        "stack-object-offset-shift\tsource-reachable-candidate\treorder-gated-362\t"
        "match-neutral\tsame-frame stack-slot offset-only residual; closing this "
        "frame residual should not be treated as the match gate\tcheckdiff-only\t"
        "\t\t0\tgenerator-gated\tlifetime-layout\t"
    ) in stack_queue
    assert "\t0.12500\tswap a <-> b\tevaluated\t3" in stack_queue
    assert (
        "99.25000\tframe_fn\tstack-layout\tframe-too-large\t"
        "\t\t\t\t"
        "frame-too-large\tunresolved-source-attribution\tgen-gated-366\t"
        "unknown\tframe relevance is not proven by the current frame taxonomy "
        "evidence\tcheckdiff-only\t\t\t0\tgenerator-gated\tframe-transform-search\t"
    ) in stack_queue

    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "| Report audit candidates | 5 |" in summary
    assert "| stack-local-layout | 3 |" in summary
    assert "| known-small-pattern-candidate | 1 |" in summary


def test_generate_inventory_writes_completed_run_status_last(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=fake_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=2,
    )

    status_path = output / "run-status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["attempted_count"] == result.attempted_count == 2
    assert status["classified_count"] == result.classified_count == 2
    assert status["error_count"] == result.error_count == 0
    assert status["report_non100_count"] == result.report_non100_count == 5
    assert status["started_at"]
    assert status["completed_at"]
    assert "failed_at" not in status


def test_generate_inventory_marks_failed_status_when_classification_crashes(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    queues = output / "queues"
    queues.mkdir(parents=True)
    stale_queue = queues / "signature-call-type.tsv"
    stale_queue.write_text(
        "match_percent\tfunction\tnext_command\n"
        "99.0\told_fn\tmelee-agent debug suggest casts old_fn\n",
        encoding="utf-8",
    )
    write_report(report)

    def crashing_runner(function: str):
        raise RuntimeError(f"boom while classifying {function}")

    with pytest.raises(RuntimeError, match="boom while classifying stack_fn"):
        generate_inventory(
            report,
            output,
            checkdiff_runner=crashing_runner,
            decl_order_evaluator=None,
            frame_report_runner=None,
            workers=1,
            limit=1,
        )

    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["attempted_count"] == 1
    assert "boom while classifying stack_fn" in status["error"]
    assert status["started_at"]
    assert status["failed_at"]
    assert "completed_at" not in status
    assert "debug suggest casts old_fn" in stale_queue.read_text(encoding="utf-8")


def test_generate_inventory_marks_failed_status_when_report_load_fails(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "broken-report.json"
    output = tmp_path / "taxonomy"
    output.mkdir()
    (output / "run-status.json").write_text(
        json.dumps({"status": "completed", "completed_at": "old"}),
        encoding="utf-8",
    )
    report.write_text("{not-json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        generate_inventory(
            report,
            output,
            checkdiff_runner=fake_checkdiff,
            decl_order_evaluator=None,
            frame_report_runner=None,
            workers=1,
        )

    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["attempted_count"] == 0
    assert status["error_type"] == "JSONDecodeError"
    assert "completed_at" not in status


def test_generate_inventory_marks_failed_before_waiting_for_sibling_worker(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    slow_started = threading.Event()
    release_slow = threading.Event()
    worker_done = threading.Event()
    worker_errors: list[BaseException] = []

    def runner(function: str):
        if function == "stack_fn":
            raise RuntimeError("boom before sibling finishes")
        if function == "small_fn":
            slow_started.set()
            release_slow.wait(timeout=2)
        return fake_checkdiff(function)

    def invoke_inventory() -> None:
        try:
            with pytest.raises(RuntimeError, match="boom before sibling finishes"):
                generate_inventory(
                    report,
                    output,
                    checkdiff_runner=runner,
                    decl_order_evaluator=None,
                    frame_report_runner=None,
                    workers=2,
                    limit=2,
                )
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            worker_done.set()

    thread = threading.Thread(target=invoke_inventory)
    thread.start()
    try:
        assert slow_started.wait(timeout=1)
        status_path = output / "run-status.json"
        for _ in range(100):
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") == "failed":
                break
            threading.Event().wait(timeout=0.01)
        else:
            pytest.fail("inventory did not mark failed before sibling worker finished")
        assert status["error_type"] == "RuntimeError"
    finally:
        release_slow.set()
        thread.join(timeout=2)
    assert worker_errors == []
    assert worker_done.is_set()


def test_generate_inventory_consumes_later_completed_worker_before_slow_earlier_one(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    completed: list[str] = []
    small_done = threading.Event()

    def runner(function: str):
        if function == "stack_fn":
            assert small_done.wait(timeout=2)
        elif function == "small_fn":
            small_done.set()
        return fake_checkdiff(function)

    def progress(event: dict[str, object]) -> None:
        if event.get("event") == "candidate_done":
            completed.append(str(event["function"]))

    generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=2,
        limit=2,
        progress_callback=progress,
    )

    assert completed[:2] == ["small_fn", "stack_fn"]


def test_generate_inventory_emits_periodic_progress_when_workers_are_busy(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    events: list[dict[str, object]] = []

    def slow_runner(function: str):
        threading.Event().wait(timeout=0.05)
        return fake_checkdiff(function)

    generate_inventory(
        report,
        output,
        checkdiff_runner=slow_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=1,
        progress_callback=events.append,
        progress_interval=0.01,
    )

    progress_events = [
        event for event in events if event.get("event") == "inventory_progress"
    ]
    assert progress_events
    assert progress_events[0]["completed_count"] == 0
    assert progress_events[0]["pending_count"] == 1
    assert progress_events[0]["active_functions"] == ["stack_fn"]


def test_offset_discrepancies_route_to_struct_offset_bucket_before_registers() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_candidate

    candidate = FunctionCandidate(
        function="struct_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )

    def runner(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "register-allocation",
                    "offset_discrepancies": [
                        {
                            "base_reg": "r31",
                            "cur_disp": 260,
                            "ref_disp": 264,
                            "opcode": "lwz",
                        }
                    ],
                    "reasons": ["offset-only field displacement mismatch"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    record, error = classify_candidate(
        candidate,
        runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["subcategory"] == "struct-field-offset-displacement"
    assert record["source_actionability"] == "current-tools-struct-verify"
    assert record["headline_tool"] == "struct-verify"
    assert record["offset_discrepancy_count"] == 1
    assert record["offset_discrepancy_bases"] == "r31"
    assert record["offset_discrepancy_disps"] == "current:260 expected:264"
    assert "melee-agent struct verify struct_fn" in record["next_command"]
    assert "--base r31" in record["next_command"]


def test_fuzzy_100_noncomplete_functions_are_audited_but_exact_matches_skip(
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
                        "name": "main/melee/demo/demo",
                        "metadata": {
                            "source_path": "src/melee/demo/demo.c",
                            "complete": False,
                        },
                        "measures": {
                            "matched_functions": 1,
                            "total_functions": 2,
                        },
                        "functions": [
                            {
                                "name": "fuzzy_exact",
                                "size": "64",
                                "fuzzy_match_percent": 100.0,
                                "metadata": {"virtual_address": "2147483648"},
                            },
                            {
                                "name": "fuzzy_offset",
                                "size": "64",
                                "fuzzy_match_percent": 100.0,
                                "metadata": {"virtual_address": "2147483712"},
                            },
                        ],
                    },
                    {
                        "name": "main/melee/demo/complete",
                        "metadata": {
                            "source_path": "src/melee/demo/complete.c",
                            "complete": True,
                        },
                        "functions": [
                            {
                                "name": "complete_fuzzy_100",
                                "size": "64",
                                "fuzzy_match_percent": 100.0,
                                "metadata": {"virtual_address": "2147483776"},
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    seen: list[str] = []

    def runner(function: str):
        seen.append(function)
        if function == "fuzzy_exact":
            return 0, json.dumps(
                {
                    "function": function,
                    "match": True,
                    "classification": {"primary": "instruction-identical"},
                    "structural": {},
                }
            ), ""
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "operand-register-or-offset",
                    "offset_discrepancies": [
                        {
                            "base_reg": "r30",
                            "cur_disp": 12,
                            "ref_disp": 16,
                        }
                    ],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
    )

    assert seen == ["fuzzy_exact", "fuzzy_offset"]
    assert result.attempted_count == 2
    assert result.classified_count == 1
    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert [row["function"] for row in records] == ["fuzzy_offset"]
    assert records[0]["work_bucket"] == "struct-offset-discrepancy"


def test_describe_actionability_splits_non_frame_work_buckets() -> None:
    from tools.function_taxonomy_inventory import describe_actionability

    cases = [
        (
            "known-small-pattern-candidate",
            "small-opcode-or-operand-pattern",
            "manual-small-pattern",
            "mismatch-db",
        ),
        (
            "signature-call-type",
            "call-shape-or-prototype",
            "current-tools-signature-audit",
            "debug-suggest-signatures",
        ),
        (
            "inline-boundary",
            "missing-reference-call-current-inlined",
            "manual-inline-guidance",
            "patterns-inlines",
        ),
        (
            "data-symbol-relocation",
            "persistent-data-symbol-or-relocation",
            "current-tools-data-symbol",
            "checkdiff-name-magic",
        ),
        (
            "indexed-struct-pointer",
            "array-indexed-vs-element-pointer",
            "current-tools-indexed-pointer",
            "source-shape",
        ),
        (
            "struct-offset-discrepancy",
            "struct-field-offset-displacement",
            "current-tools-struct-verify",
            "struct-verify",
        ),
        (
            "structural-reconstruction",
            "branch-or-control-flow-shape",
            "structural-rebuild",
            "control-flow-shape-search",
        ),
        (
            "structural-reconstruction",
            "opcode-sequence-diff",
            "opcode-reconstruction",
            "opseq-mismatch-db",
        ),
        (
            "structural-reconstruction",
            "direct-inspection-needed",
            "backend-ceiling",
            "manual-inspection",
        ),
        (
            "register-allocator",
            "register-only-needs-pcdump-proof",
            "pcdump-proof-needed",
            "mwcc-debug",
        ),
    ]

    for bucket, subcategory, actionability, headline in cases:
        result = describe_actionability(bucket, subcategory)
        assert result["source_actionability"] == actionability
        assert result["headline_tool"] == headline

    signature = describe_actionability("signature-call-type", "argument-bank")
    assert signature["source_actionability"] == "current-tools-signature-audit"
    assert signature["headline_tool"] == "debug-suggest-signatures"
    assert "signature audit" in signature["actionability_reason"]


def test_signature_call_type_next_command_routes_to_signature_audit() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, next_command

    candidate = FunctionCandidate(
        function="fn_80000000",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        address="0x80000000",
        size_bytes=128,
        match_percent=98.5,
        object_status="NonMatching",
    )

    command = next_command("signature-call-type", "argument-bank", candidate)

    assert command == (
        "melee-agent debug suggest signatures -f fn_80000000 "
        "--source-file src/melee/demo/demo.c --json"
    )


def test_signature_call_type_next_command_omits_empty_source_file() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, next_command

    candidate = FunctionCandidate(
        function="fn_80000000",
        unit="main/melee/demo/demo",
        file_path="",
        address="0x80000000",
        size_bytes=128,
        match_percent=98.5,
        object_status="NonMatching",
    )

    command = next_command("signature-call-type", "argument-bank", candidate)

    assert command == "melee-agent debug suggest signatures -f fn_80000000 --json"


def test_bss_anchor_classification_buckets_as_ceiling() -> None:
    from tools.function_taxonomy_inventory import (
        FunctionCandidate,
        classify_bucket,
        describe_actionability,
    )

    candidate = FunctionCandidate(
        function="fn_80181C80",
        unit="main/melee/gm/gm_1A36",
        file_path="melee/gm/gm_1A36.c",
        size_bytes=220,
        match_percent=99.5,
        address="0x80181c80",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "instruction-sequence",
            "bss_anchor_relocations": {
                "status": "ceiling",
                "pairs": [
                    {
                        "offset": "004",
                        "kind": "R_PPC_ADDR16_HA",
                        "named_symbol": "lbl_80472ED8",
                        "anchor_symbol": "...bss.0",
                        "named_side": "expected",
                    }
                ],
            },
        }
    }

    bucket, subcategory, small = classify_bucket(candidate, payload)

    assert (bucket, subcategory, small) == (
        "data-symbol-relocation",
        "bss-section-anchor-ceiling",
        False,
    )
    actionability = describe_actionability(bucket, subcategory)
    assert actionability["source_actionability"] == "ceiling"
    assert actionability["headline_tool"] == "checkdiff-name-magic"


def test_structural_branch_next_command_uses_control_flow_shape_search() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, next_command

    candidate = FunctionCandidate(
        function="demo_fn",
        unit="main/melee/demo",
        file_path="melee/demo.c",
        size_bytes=128,
        match_percent=97.0,
        address="0x80000000",
        object_status="NonMatching",
    )

    command = next_command(
        "structural-reconstruction",
        "branch-or-control-flow-shape",
        candidate,
    )

    assert "debug mutate control-flow-shape-search -f demo_fn" in command
    assert "--source-file src/melee/demo.c" in command
    assert "--compile-probes" in command
    assert "--json" in command


def test_known_small_pattern_queue_has_no_current_tools_harvest_rows(
    tmp_path: Path,
) -> None:
    from src.harvest import HarvestFilters, load_queue_rows
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    generate_inventory(
        report,
        output,
        checkdiff_runner=fake_checkdiff,
        decl_order_evaluator=fake_decl_order_evaluator,
        frame_report_runner=None,
        workers=1,
    )

    rows = load_queue_rows(
        output / "queues" / "known-small-pattern-candidate.tsv",
        work_bucket="known-small-pattern-candidate",
        repo_root=REPO_ROOT,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-small-pattern",)}
        ),
    )

    assert rows == []


def test_signature_queue_routes_to_advisory_audit_without_harness(
    tmp_path: Path,
) -> None:
    from src.harvest import HarvestFilters, load_queue_rows, select_harness

    queues = tmp_path / "queues"
    queues.mkdir()
    (queues / "signature-call-type.tsv").write_text(
        (
            "match_percent\tfunction\tprimary\tsubcategory\t"
            "source_actionability\theadline_tool\tactionability_reason\t"
            "file_path\tnext_command\n"
            "99.5\tsig_fn\tsignature-type-mismatch\tcall-shape-or-prototype\t"
            "current-tools-signature-audit\tdebug-suggest-signatures\t"
            "signature audit rebucket guidance\tmelee/demo/demo.c\t"
            "melee-agent debug suggest signatures -f sig_fn "
            "--source-file src/melee/demo/demo.c --json\n"
        ),
        encoding="utf-8",
    )
    (queues / "inline-boundary.tsv").write_text(
        (
            "match_percent\tfunction\tprimary\tsubcategory\t"
            "source_actionability\theadline_tool\tactionability_reason\t"
            "file_path\tnext_command\n"
            "99.5\tinline_fn\tinline-boundary-toolchain-artifact\t"
            "missing-reference-call-current-inlined\tmanual-inline-guidance\t"
            "patterns-inlines\tmanual inline guidance\tmelee/demo/demo.c\t"
            "melee-agent patterns inlines src/melee/demo/demo.c\n"
        ),
        encoding="utf-8",
    )

    signature = load_queue_rows(
        queues / "signature-call-type.tsv",
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-signature-audit",)}
        ),
    )
    assert len(signature) == 1
    assert signature[0].headline_tool == "debug-suggest-signatures"
    assert select_harness(signature[0]) is None

    assert (
        load_queue_rows(
            queues / "inline-boundary.tsv",
            work_bucket="inline-boundary",
            repo_root=REPO_ROOT,
            filters=HarvestFilters(
                where={"source_actionability": ("current-tools-inline",)}
            ),
        )
        == []
    )


def test_completed_inventory_signature_queue_routes_to_debug_suggest_signatures(
    tmp_path: Path,
) -> None:
    from src.harvest import preview_harvest_queue
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/signature_demo",
                        "metadata": {
                            "source_path": "src/melee/demo/signature_demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "signature_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147487000"},
                            }
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
                    "primary": "signature-type-mismatch",
                    "reasons": ["call shape differs after signature audit"],
                },
                "structural": {"opcode_similarity": 0.999, "line_delta": 0},
            }
        ), ""

    def cast_audit_runner(_candidate):
        return {
            "status": "ok",
            "medium_plus_count": 1,
            "high_count": 0,
            "medium_count": 1,
            "low_count": 0,
        }

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=cast_audit_runner,
        workers=1,
    )

    assert result.classified_count == 1
    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"

    queue_text = (output / "queues" / "signature-call-type.tsv").read_text(
        encoding="utf-8"
    )
    assert "debug suggest signatures -f signature_fn" in queue_text
    assert "debug suggest casts" not in queue_text

    preview = preview_harvest_queue(
        output / "queues" / "signature-call-type.tsv",
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
    )
    assert preview["sample"][0]["next_command"] == (
        "melee-agent debug suggest signatures -f signature_fn "
        "--source-file src/melee/demo/signature_demo.c --json"
    )


def test_generate_inventory_records_checkdiff_timeout_error(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    def timeout_checkdiff(function: str):
        if function == "stack_fn":
            raise subprocess.TimeoutExpired(
                cmd=["tools/checkdiff.py", function],
                timeout=1.5,
                output="partial stdout",
                stderr="partial stderr",
            )
        return fake_checkdiff(function)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=timeout_checkdiff,
        decl_order_evaluator=fake_decl_order_evaluator,
        frame_report_runner=None,
        workers=2,
        limit=1,
    )

    assert result.classified_count == 0
    assert result.error_count == 1
    errors = read_jsonl(output / "checkdiff-errors.jsonl")
    assert errors[0]["function"] == "stack_fn"
    assert errors[0]["error"] == "checkdiff_timeout"
    assert "timed out after 1.5s" in errors[0]["message"]
    assert "partial stdout" in errors[0]["stdout_tail"]
    assert "partial stderr" in errors[0]["stderr_tail"]


def test_default_decl_order_evaluator_reports_timeout(monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    candidate = inventory.FunctionCandidate(
        function="stack_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=384,
        match_percent=99.75,
        address="0x8000000c",
        object_status="NonMatching",
    )

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=kwargs.get("args") or args[0],
            timeout=kwargs.get("timeout"),
            output="decl stdout",
            stderr="decl stderr",
        )

    monkeypatch.setattr(inventory.subprocess, "run", timeout_run)

    summary = inventory.default_decl_order_evaluator(candidate, {})

    assert summary["evaluated_status"] == "unevaluated: decl-orders timed out"
    assert summary["candidate_count"] == 0
    assert summary["best_decl_delta"] is None
    assert "decl stdout" in summary["stdout_tail"]
    assert "decl stderr" in summary["stderr_tail"]


def test_signature_bucket_requires_medium_cast_evidence() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="ftDemo_80000000",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=512,
        match_percent=99.1,
        address="0x80000000",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "signature-type-mismatch",
            "reasons": ["call shape differs after alignment"],
        },
        "structural": {"opcode_similarity": 0.99, "line_delta": 2},
    }

    assert classify_bucket(candidate, payload, cast_audit={"medium_plus_count": 1}) == (
        "signature-call-type",
        "call-shape-or-prototype",
        False,
    )
    assert classify_bucket(candidate, payload, cast_audit={"medium_plus_count": 0}) == (
        "structural-reconstruction",
        "branch-or-control-flow-shape",
        False,
    )


def test_signature_red_herring_rebuckets_by_dominant_residual() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="ftCo_800CF6E8",
        unit="main/melee/ft/ftcommon",
        file_path="melee/ft/ftcommon.c",
        size_bytes=2048,
        match_percent=99.0,
        address="0x800cf6e8",
        object_status="NonMatching",
    )

    frame_payload = {
        "classification": {
            "primary": "signature-type-mismatch",
            "reasons": [
                "call shape differs; check prototypes",
                "frame reservation gap is too small",
            ],
            "stack_frame_delta": {"missing_stack_bytes": 32},
        },
        "structural": {"opcode_similarity": 0.98, "line_delta": 4},
    }
    assert classify_bucket(candidate, frame_payload, cast_audit={"medium_plus_count": 0}) == (
        "stack-local-layout",
        "frame-too-small",
        False,
    )

    data_payload = {
        "classification": {
            "primary": "signature-type-mismatch",
            "reasons": [
                "call shape differs; check prototypes",
                "578 differing paired lines reference data/symbol relocations",
            ],
        },
        "structural": {"opcode_similarity": 0.999, "line_delta": 1},
    }
    assert classify_bucket(candidate, data_payload, cast_audit={"medium_plus_count": 0}) == (
        "data-symbol-relocation",
        "signature-red-herring-data-symbol",
        False,
    )


def test_inventory_help_renders_literal_percent() -> None:
    from tools.function_taxonomy_inventory import build_arg_parser

    help_text = build_arg_parser().format_help()

    assert ">=99% stack-" in help_text
    assert "local-layout rows" in help_text
    assert "option_strings" not in help_text


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

    assert result.report_non100_count == 5
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
                        "stack_slot_localizer": {
                            "frame_size": 64,
                            "mismatch_count": 1,
                            "deltas": [4],
                        },
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
    assert pure["frame_match_relevance"] == "match-gating-candidate"
    assert pure["frame_verdict"] == "source-reachable-candidate"
    assert pure["frame_attribution_status"] == "checkdiff-only"
    assert pure["next_command"] == pure["frame_next_command"]
    assert "frame-transform-search" in pure["next_command"]
    assert pure["source_actionability"] == "current-tools"

    same_slot = records["same_slot_fn"]
    assert same_slot["frame_cause"] == "stack-object-offset-shift"
    assert same_slot["frame_closability_tier"] == "reorder-gated-362"
    assert same_slot["frame_match_relevance"] == "match-neutral"
    assert same_slot["source_actionability"] == "generator-gated"

    low_spill = records["low_spill_fn"]
    assert low_spill["frame_cause"] == "reserved-unused-low-spill-region"
    assert low_spill["frame_closability_tier"] == "ceiling"
    assert low_spill["frame_raw_cause"] == "reserved-unused-low-spill-region"
    assert low_spill["source_actionability"] == "ceiling"

    csv_text = (output / "taxonomy.records.csv").read_text(encoding="utf-8")
    assert "frame_closability_tier" in csv_text.splitlines()[0]
    assert "frame_match_relevance" in csv_text.splitlines()[0]
    assert "frame_match_relevance_reason" in csv_text.splitlines()[0]
    assert "frame_source_object_symbol" in csv_text.splitlines()[0]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    assert "frame_match_relevance" in stack_queue.splitlines()[0]
    assert "frame_match_relevance_reason" in stack_queue.splitlines()[0]
    header = stack_queue.splitlines()[0]
    assert "frame_cause" in header
    assert "frame_verdict" in header
    assert "frame_closability_tier" in header
    assert "frame_next_command" in header
    assert "cast_medium_plus_count" in header


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
