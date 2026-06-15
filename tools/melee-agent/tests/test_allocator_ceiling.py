import json

import pytest
from typer.testing import CliRunner

from src.cli import debug as cli_debug

from src.mwcc_debug.allocator_ceiling import (
    EvidenceFormatError,
    EvidenceFunctionMismatch,
    classify_allocator_ceiling,
    flatten_evidence_items,
)


def _solve_delta(function="fn_test"):
    return {
        "function": function,
        "class_id": 0,
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": function,
            "blocker": "structurally-different-virtual",
            "missing_virtuals": [{"target_ig": 40}],
        },
    }


def _bare_delta(function="fn_test"):
    return {
        "kind": "node-set-delta",
        "function": function,
        "blocker": "structurally-different-virtual",
        "missing_virtuals": [{"target_ig": 40}],
    }


def _force_match(function="fn_test"):
    return {
        "function": function,
        "force_vector_verify": {
            "ran": True,
            "union": {"status": "match", "returncode": 0},
        },
    }


def _node_wrong(function="fn_test"):
    return {
        "function": function,
        "status": "exhausted",
        "wrong_register_exhausted": True,
        "objective_counts": {"wrong-register": 6},
        "exhaustive": True,
    }


def _transform_negative(function="fn_test"):
    return {
        "function": function,
        "validation_summary": {
            "stop_condition": "exhausted-negative-evidence",
            "evaluated_probes": 6,
            "remaining_probe_ids": [],
            "outcomes": {"negative-evidence": 6},
        },
        "node_set_delta_summary": {
            "provided": True,
            "missing_count": 3,
            "bindable_count": 2,
            "skipped_count": 1,
            "omitted_count": 0,
        },
    }


def _directed_exhausted(function="fn_test"):
    blocked = [
        {
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
        }
    ]
    return {
        "function": function,
        "unit": "melee/mn/mndiagram",
        "gate": {
            "passed": False,
            "reason": "no_smooth_gradient",
            "evidence": {
                "n_treatment": 3,
                "best_delta": 0.0,
            },
        },
        "directed_telemetry": [
            {
                "valid": True,
                "applied_mutator": "transform-corpus:coloring_register_steering:0",
                "checkdiff_gate": "byte_mismatch",
                "proof_assignments": {
                    "satisfied": [],
                    "blocked": blocked,
                    "abstained": [],
                },
                "non_actionable": False,
            },
            {
                "valid": True,
                "applied_mutator": "reorder_local_decls",
                "checkdiff_gate": "byte_mismatch",
                "proof_assignments": {
                    "satisfied": [],
                    "blocked": blocked,
                    "abstained": [],
                },
                "non_actionable": True,
            },
        ],
        "accounting": {
            "compiled": 2,
            "budget_exhausted": False,
            "source_shape_drained": True,
            "producer_failed": 0,
        },
    }


def test_practical_ceiling_requires_all_negative_proofs():
    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "target-only-allocator-rotation"
    assert result["source_shape_exhausted"] is True
    assert result["wrong_register_exhausted"] is True
    assert result["node_set_delta"]["blocker"] == "structurally-different-virtual"
    assert result["force_vector"]["union_status"] == "match"
    assert result["exit_code"] == 3


def test_positive_proof_wins_over_negative_evidence():
    improved = dict(_node_wrong(), status="improved", best_checkdiff_delta=0.25)

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), improved, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "actionable"
    assert result["positive_proofs"]
    assert result["exit_code"] == 0


def test_bounded_transform_omitted_probe_blocks_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["omitted_count"] = 1

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "transform-corpus omitted 1 node-set probe" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_bounded_transform_capped_probe_blocks_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["capped_count"] = 1

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "transform-corpus capped 1 node-set probe" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_skipped_unbindable_transform_evidence_does_not_block_ceiling():
    transform = _transform_negative()
    transform["node_set_delta_summary"]["skipped_count"] = 2

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), _node_wrong(), transform],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["skipped_source_evidence_count"] == 2


def test_missing_force_vector_is_incomplete_not_ceiling():
    result = classify_allocator_ceiling(
        [_solve_delta(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert "force-phys verification with union status match" in result["missing_evidence"]
    assert result["exit_code"] == 3


def test_force_vector_match_without_run_is_incomplete():
    force = _force_match()
    force["force_vector_verify"]["ran"] = False

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["ran"] is False
    assert result["force_vector"]["union_status"] == "match"
    assert "force-phys verification with union status match" in result["missing_evidence"]


def test_force_vector_prefers_ran_match_over_stale_match():
    stale_force = _force_match()
    stale_force["force_vector_verify"]["ran"] = False
    valid_force = _force_match()

    result = classify_allocator_ceiling(
        [_solve_delta(), stale_force, valid_force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["force_vector"]["ran"] is True
    assert result["force_vector"]["union_status"] == "match"
    assert result["missing_evidence"] == []


def test_force_vector_fallback_prefers_executed_no_match_over_stale_match():
    stale_force = _force_match()
    stale_force["force_vector_verify"]["ran"] = False
    executed_force = _force_match()
    executed_force["force_vector_verify"]["union"]["status"] = "no_match"

    result = classify_allocator_ceiling(
        [_solve_delta(), stale_force, executed_force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["ran"] is True
    assert result["force_vector"]["union_status"] == "no_match"


def test_force_vector_no_match_is_incomplete():
    force = _force_match()
    force["force_vector_verify"]["union"]["status"] = "no_match"

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["union_status"] == "no_match"
    assert "force-phys verification with union status match" in result["missing_evidence"]


def test_function_mismatch_rejected_in_nested_payload():
    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_solve_delta("other_fn"), _force_match(), _node_wrong()],
            function="fn_test",
        )


def test_unscoped_evidence_rejected():
    unscoped = {
        "status": "exhausted",
        "wrong_register_exhausted": True,
    }

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([unscoped], function="fn_test")


def test_bare_node_set_delta_payload_counts_as_required_delta():
    result = classify_allocator_ceiling(
        [_bare_delta(), _force_match(), _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "practical-ceiling"
    assert result["node_set_delta"]["function"] == "fn_test"


def test_bounded_candidate_limit_blocks_ceiling():
    node = dict(_node_wrong(), stop_reason="candidate-limit")

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "candidate-limit" in " ".join(result["bounded_reasons"])
    assert result["exit_code"] == 4


def test_bounded_budget_blocks_ceiling():
    node = dict(_node_wrong(), stop_condition={"kind": "budget-exhausted"})

    result = classify_allocator_ceiling(
        [_solve_delta(), _force_match(), node, _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "bounded"
    assert "budget-exhausted" in " ".join(result["bounded_reasons"])


def test_directed_exhausted_byte_mismatches_classify_as_practical_ceiling():
    result = classify_allocator_ceiling([_directed_exhausted()], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["terminal_reason"] == "directed-source-exhausted"
    assert result["directed_source_exhausted"] is True
    assert result["source_shape_exhausted"] is True
    assert result["backend_blockers"] == [
        {
            "original_ig": 32,
            "new_ig": 32,
            "desired_phys": 28,
            "assigned_phys": 26,
            "mutators": [
                "transform-corpus:coloring_register_steering:0",
                "reorder_local_decls",
            ],
        }
    ]
    assert result["exit_code"] == 3


def test_directed_backend_blockers_keep_register_class_identity():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"] = [
        {
            "class_id": 0,
            "valid": True,
            "applied_mutator": "transform-corpus:gpr",
            "checkdiff_gate": "byte_mismatch",
            "proof_assignments": {
                "satisfied": [],
                "blocked": [
                    {
                        "original_ig": 7,
                        "new_ig": 7,
                        "desired_phys": 2,
                        "assigned_phys": 3,
                    }
                ],
                "abstained": [],
            },
        },
        {
            "class_id": 1,
            "valid": True,
            "applied_mutator": "transform-corpus:fpr",
            "checkdiff_gate": "byte_mismatch",
            "proof_assignments": {
                "satisfied": [],
                "blocked": [
                    {
                        "original_ig": 7,
                        "new_ig": 7,
                        "desired_phys": 2,
                        "assigned_phys": 3,
                    }
                ],
                "abstained": [],
            },
        },
    ]

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert result["backend_blockers"] == [
        {
            "class_id": 0,
            "original_ig": 7,
            "new_ig": 7,
            "desired_phys": 2,
            "assigned_phys": 3,
            "mutators": ["transform-corpus:gpr"],
        },
        {
            "class_id": 1,
            "original_ig": 7,
            "new_ig": 7,
            "desired_phys": 2,
            "assigned_phys": 3,
            "mutators": ["transform-corpus:fpr"],
        },
    ]


def test_directed_byte_match_is_actionable():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"][0]["checkdiff_gate"] = "byte_match"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "actionable"
    assert "directed byte_match" in result["positive_proofs"]
    assert result["directed_source_exhausted"] is False
    assert result["backend_blockers"] == []
    assert result["exit_code"] == 0


def test_directed_without_blocked_assignments_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row["proof_assignments"]["blocked"] = []

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert (
        "directed telemetry with blocked proof assignments"
        in result["missing_evidence"]
    )


def test_directed_without_source_transform_rows_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row["applied_mutator"] = "force_phys_assignment"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert (
        "directed telemetry from source-transform candidates"
        in result["missing_evidence"]
    )


def test_directed_unknown_byte_outcome_is_incomplete():
    evidence = _directed_exhausted()
    for row in evidence["directed_telemetry"]:
        row.pop("checkdiff_gate")

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed byte-mismatch outcomes" in result["missing_evidence"]


def test_directed_without_source_shape_drained_signal_is_incomplete():
    evidence = _directed_exhausted()
    evidence["accounting"].pop("source_shape_drained")

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "incomplete"
    assert "directed source-shape drained signal" in result["missing_evidence"]


def test_directed_gate_progress_is_actionable_not_ceiling():
    evidence = _directed_exhausted()
    evidence["gate"]["passed"] = True
    evidence["gate"]["reason"] = "attributable_progress"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "actionable"
    assert "directed attributable_progress" in result["positive_proofs"]
    assert result["directed_source_exhausted"] is False
    assert result["backend_blockers"] == []


def test_directed_budget_exhaustion_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["budget_exhausted"] = True

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search budget exhausted" in result["bounded_reasons"]
    assert result["exit_code"] == 4


def test_directed_producer_failure_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["producer_failed"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search producer failed" in result["bounded_reasons"]


def test_directed_score_failure_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["score_failed"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search score failed" in result["bounded_reasons"]


def test_directed_invalid_telemetry_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["directed_invalid"] = 1

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search invalid directed telemetry" in result["bounded_reasons"]


def test_directed_invalid_telemetry_row_is_bounded_without_accounting_counter():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"].append(
        {
            "valid": False,
            "invalid_reason": "pcdump_missing",
            "applied_mutator": "transform-corpus:coloring_register_steering:bad",
        }
    )

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search invalid directed telemetry" in result["bounded_reasons"]


def test_directed_compile_failures_with_scored_rows_do_not_bound():
    evidence = _directed_exhausted()
    evidence["accounting"]["compile_failed"] = 2

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "practical-ceiling"
    assert "directed search compile failed" not in result["bounded_reasons"]


def test_directed_candidate_limit_is_bounded():
    evidence = _directed_exhausted()
    evidence["accounting"]["stop_reason"] = "candidate-limit"

    result = classify_allocator_ceiling([evidence], function="fn_test")

    assert result["status"] == "bounded"
    assert "directed search candidate-limit" in result["bounded_reasons"]


@pytest.mark.parametrize("union_status", ["inconclusive", "timeout", "failed"])
def test_force_vector_non_match_statuses_are_incomplete(union_status):
    force = _force_match()
    force["force_vector_verify"]["union"]["status"] = union_status

    result = classify_allocator_ceiling(
        [_solve_delta(), force, _node_wrong(), _transform_negative()],
        function="fn_test",
    )

    assert result["status"] == "incomplete"
    assert result["force_vector"]["union_status"] == union_status


def test_function_mismatch_rejected_in_summary_payload():
    transform = _transform_negative()
    transform["validation_summary"]["function"] = "other_fn"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling(
            [_solve_delta(), _force_match(), _node_wrong(), transform],
            function="fn_test",
        )


def test_function_mismatch_rejected_in_validation_row():
    validation = {
        "function": "fn_test",
        "validation": [
            {
                "function": "other_fn",
                "outcome": "retained-source-improvement",
            }
        ],
    }

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([validation], function="fn_test")


def test_function_mismatch_rejected_in_validator_payload():
    validation = {
        "function": "fn_test",
        "validation": [
            {
                "outcome": "retained-source-improvement",
                "validator_payload": {"function": "other_fn"},
            }
        ],
    }

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([validation], function="fn_test")


def test_function_mismatch_rejected_in_directed_telemetry_row():
    evidence = _directed_exhausted()
    evidence["directed_telemetry"][0]["function"] = "other_fn"

    with pytest.raises(EvidenceFunctionMismatch):
        classify_allocator_ceiling([evidence], function="fn_test")


def test_flatten_rejects_invalid_scalar_evidence():
    with pytest.raises(EvidenceFormatError):
        flatten_evidence_items([123])


def test_flatten_rejects_invalid_scalar_inside_list():
    with pytest.raises(EvidenceFormatError):
        flatten_evidence_items([[{"function": "fn_test"}, "bad"]])


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_allocator_ceiling_cli_json_practical_ceiling(tmp_path):
    evidence_path = _write_json(
        tmp_path / "evidence.json",
        [_solve_delta(), _force_match(), _node_wrong(), _transform_negative()],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["terminal_reason"] == "target-only-allocator-rotation"


def test_allocator_ceiling_cli_text_lists_next_steps(tmp_path):
    evidence_path = _write_json(tmp_path / "evidence.json", [_solve_delta()])
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: incomplete" in result.output
    assert "force-phys verification with union status match" in result.output


def test_allocator_ceiling_cli_text_lists_backend_blockers(tmp_path):
    evidence_path = _write_json(tmp_path / "directed.json", _directed_exhausted())
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 3
    assert "allocator-ceiling fn_test: practical-ceiling" in result.output
    assert "backend blockers:" in result.output
    assert "ig32->ig32 wants 28 got 26" in result.output


def test_allocator_ceiling_cli_rejects_mixed_function(tmp_path):
    evidence_path = _write_json(tmp_path / "evidence.json", [_solve_delta("other_fn")])
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
        "--json",
    ])

    assert result.exit_code == 2
    assert "not fn_test" in result.output


def test_allocator_ceiling_cli_rejects_unscoped_evidence(tmp_path):
    evidence_path = _write_json(
        tmp_path / "evidence.json",
        [{"status": "exhausted", "wrong_register_exhausted": True}],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 2
    assert "has no function scope" in result.output


def test_allocator_ceiling_cli_accepts_multiple_evidence_files(tmp_path):
    solve_path = _write_json(tmp_path / "solve.json", _bare_delta())
    rest_path = _write_json(
        tmp_path / "rest.json",
        [_force_match(), _node_wrong(), _transform_negative()],
    )
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(solve_path),
        "--evidence", str(rest_path),
        "--json",
    ])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["status"] == "practical-ceiling"
    assert payload["evidence_count"] == 4


@pytest.mark.parametrize("payload", [123, [{"function": "fn_test"}, "bad"]])
def test_allocator_ceiling_cli_rejects_invalid_evidence_shape(tmp_path, payload):
    evidence_path = _write_json(tmp_path / "bad.json", payload)
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(evidence_path),
    ])

    assert result.exit_code == 2
    assert "evidence must be a JSON object" in result.output


def test_allocator_ceiling_cli_rejects_missing_file(tmp_path):
    runner = CliRunner()

    result = runner.invoke(cli_debug.solve_app, [
        "allocator-ceiling",
        "--function", "fn_test",
        "--evidence", str(tmp_path / "missing.json"),
    ])

    assert result.exit_code == 2
    assert "could not read --evidence" in result.output
