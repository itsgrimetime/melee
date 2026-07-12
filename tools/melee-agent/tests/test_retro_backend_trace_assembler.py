import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_schema, backend_trace_assembler  # noqa: E402
from tools.mwcc_retro.backend_instrumentation_proof import proof_sha256  # noqa: E402

from tests.test_retro_backend_object_bindings import (  # noqa: E402
    lifetime_coverage,
    minimal_object_bindings,
    trusted_proof,
)
from tests.test_retro_backend_pcode_lineage import _candidate_elf  # noqa: E402

COMPILER = {"family": "MWCC", "version": "GC/1.2.5n", "retail": True}
FIXTURE_ROOT = REPO / "tools/melee-agent/tests/fixtures/retro"
SOURCE = {
    "tu": "src/melee/test/unit.c",
    "function": "candidate_fn",
    "mwcc_command": "test mwcc command candidate candidate_fn",
    "mwcc_command_hash": "sha256:d673911e77f8e9f1945c4c85d7908512517c76d9aee542551bbf918cddd8162b",
}


def _function_start() -> dict:
    return {"event": "function_start", "name": "candidate_fn"}


def _pcode_events() -> list[dict]:
    return [
        _function_start(),
        {"event": "backend_marker", "name": "pcode_pass_boundary"},
        {
            "event": "block",
            "id": "B0",
            "order": 0,
            "succ": [],
            "pred": [],
            "labels": [],
        },
        {
            "event": "pcode_instruction",
            "pass_id": "pcode_snapshot",
            "pass_name": "PCode Snapshot",
            "id": "p0",
            "block_id": "B0",
            "order": 0,
            "opcode": "mr",
            "operands": "",
            "normalized": "mr",
        },
    ]


def _regclass_event() -> dict:
    return {
        "event": "regclass",
        "class_name": "gpr",
        "class_id": 0,
        "registers": {
            "physical_count": 32,
            "allocatable": [0, 3, 4, 31],
            "initial_volatile": [0, 3, 4],
            "reserved": [1, 2],
            "fixed": [{"phys": 1, "reason": "stack_pointer"}],
            "precolored": [],
            "nonvolatile_dispense_order": [31],
            "model_boundary": [{"name": "LR", "reason": "outside-v1"}],
        },
        "non_allocatable_state": {"status": "model-boundary"},
    }


def _node(ig_id: int) -> dict:
    return {
        "event": "node",
        "class_name": "gpr",
        "class_id": 0,
        "ig_id": ig_id,
        "virtual": {"kind": "r", "number": ig_id},
        "first_def": {"status": "unavailable", "reason": "fixture"},
        "source_attribution": {"status": "unattributed", "confidence": "fixture"},
        "live": {"blocks": [], "intervals": [], "confidence": "fixture"},
        "degree": 1,
        "flags": [],
        "coalesce": {"root_ig_id": ig_id, "aliases": []},
        "simplify_order": None,
        "select_order": None,
        "assigned_phys": None,
        "spill": {"spilled": False, "reason": None},
        "color_status": "uncolored",
        "coalesced_into": None,
        "color_decision_ref": None,
    }


def _partial_decision() -> dict:
    return {
        "event": "color_decision",
        "class_name": "gpr",
        "class_id": 0,
        "id": "gpr-c0",
        "ig_id": 32,
        "iter": 0,
        "assigned_phys": 0,
        "node_state_before_select": {
            "status": "unavailable",
            "reason": "retail-post-colorgraph-only",
        },
        "reserved_or_precolored_filtered": [],
        "available_phys_ordered": [],
        "blocked_candidates": [],
        "candidate_phys_ordered": [0],
        "chosen_source": "observed-retail-assignment",
        "volatile_pool_before": [],
        "volatile_pool_after": [],
        "nonvolatile_dispense_before": {},
        "nonvolatile_dispense_after": {},
        "tie_rule": "unavailable-retail-post-colorgraph",
        "blocked_by": [],
        "decision_rule": "retail-post-colorgraph-observed-assignment",
        "confidence": "observed-partial",
        "provenance": "retail-colorgraph-return",
        "source_stage": "colorgraph_return",
    }


def _ig_events(include_partial: bool = True) -> list[dict]:
    events = [
        _function_start(),
        {"event": "backend_marker", "name": "codegen_start"},
        _regclass_event(),
        _node(32),
        _node(33),
        {
            "event": "edge",
            "class_name": "gpr",
            "class_id": 0,
            "a": 32,
            "b": 33,
        },
        {
            "event": "coalesce_mapping_empty",
            "class_name": "gpr",
            "class_id": 0,
        },
        {
            "event": "simplify_order",
            "class_name": "gpr",
            "class_id": 0,
            "order": [33, 32],
        },
        {
            "event": "select_order",
            "class_name": "gpr",
            "class_id": 0,
            "order": [33, 32],
        },
    ]
    if include_partial:
        events.append(_partial_decision())
    return events


def _frame_events() -> list[dict]:
    return [
        {
            "event": "frame_state",
            "function": "candidate_fn",
            "source_stage": "final_scheduler",
            "provenance": "frame_locals",
            "base_size_bytes": 16,
            "call_args_size_bytes": 0,
            "objects": [
                {
                    "area": "locals",
                    "name": "tmp",
                    "stack_offset": -4,
                    "size": 4,
                    "type": "s32",
                    "confidence": "observed",
                    "provenance": "frame_locals",
                }
            ],
        }
    ]


def _exact_decision(
    *,
    decision_id: str = "gpr-i0",
    ig_id: int = 32,
    iteration: int = 0,
    assigned_phys: int = 0,
) -> dict:
    return {
        "event": "color_decision",
        "class_name": "gpr",
        "class_id": 0,
        "id": decision_id,
        "ig_id": ig_id,
        "iter": iteration,
        "assigned_phys": assigned_phys,
        "node_state_before_select": {
            "precolored": False,
            "coalesced": False,
            "spill_marked": False,
            "rematerialized": False,
        },
        "reserved_or_precolored_filtered": [1, 2],
        "available_phys_ordered": [0, 3, 4],
        "blocked_candidates": [],
        "candidate_phys_ordered": [assigned_phys, *[phys for phys in [0, 3, 4] if phys != assigned_phys]],
        "chosen_source": "volatile_pool",
        "volatile_pool_before": [0, 3, 4],
        "volatile_pool_after": [3, 4],
        "nonvolatile_dispense_before": {"next": None, "remaining": []},
        "nonvolatile_dispense_after": {"consumed": None, "remaining": []},
        "tie_rule": "first_volatile_available",
        "blocked_by": [],
        "decision_rule": "lowest_available_or_nonvolatile_dispense",
        "confidence": "observed-internal",
        "provenance": "retail-colorgraph-internal",
        "source_stage": "colorgraph",
    }


def test_assemble_candidate_trace_replaces_matching_partial_decisions() -> None:
    trace = backend_trace_assembler.assemble_candidate_trace(
        pcode_events=_pcode_events(),
        ig_events=_ig_events(include_partial=True),
        frame_events=_frame_events(),
        colorgraph_events=[
            _function_start(),
            _exact_decision(decision_id="gpr-i0", ig_id=32, iteration=1, assigned_phys=0),
            _exact_decision(decision_id="gpr-i1", ig_id=33, iteration=0, assigned_phys=3),
        ],
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    assert backend_schema.validate_backend_trace(trace) == []
    fn = trace["functions"][0]
    cls = fn["regalloc"]["classes"][0]
    nodes = {node["ig_id"]: node for node in cls["nodes"]}
    assert fn["pcode"]["passes"][0]["instructions"][0]["opcode"] == "mr"
    assert [decision["id"] for decision in cls["color_decisions"]] == ["gpr-i0", "gpr-i1"]
    assert nodes[32]["assigned_phys"] == 0
    assert nodes[32]["color_decision_ref"] == "gpr-i0"
    assert nodes[33]["assigned_phys"] == 3
    assert nodes[33]["color_decision_ref"] == "gpr-i1"


def test_assemble_candidate_trace_rejects_leftover_partial_decisions() -> None:
    with pytest.raises(ValueError, match="leftover partial color decisions"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[_function_start()],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_rejects_mismatched_colorgraph_function() -> None:
    with pytest.raises(ValueError, match="colorgraph function_start mismatch"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[{"event": "function_start", "name": "other_fn"}, _exact_decision()],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_rejects_exact_partial_assignment_disagreement() -> None:
    exact = _exact_decision()
    exact["assigned_phys"] = 3
    exact["candidate_phys_ordered"] = [0, 3, 4]

    with pytest.raises(ValueError, match="exact/partial assigned_phys mismatch"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[_function_start(), exact],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_rejects_duplicate_exact_decisions() -> None:
    with pytest.raises(ValueError, match="duplicate exact color decision"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=True),
            frame_events=_frame_events(),
            colorgraph_events=[_function_start(), _exact_decision(), _exact_decision()],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_assemble_candidate_trace_requires_frame_state() -> None:
    with pytest.raises(ValueError, match="candidate trace requires frame_state"):
        backend_trace_assembler.assemble_candidate_trace(
            pcode_events=_pcode_events(),
            ig_events=_ig_events(include_partial=False),
            frame_events=[],
            colorgraph_events=[],
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )


def test_frame_events_from_map_probe_payload_converts_probe_frame_shape() -> None:
    payload = {
        "events": [
            {
                "stage": "final_scheduler",
                "frame_state": {
                    "locals": {
                        "va": 0x587FB8,
                        "head": 0x710000,
                        "objects_sample": [
                            {
                                "node": 0x710000,
                                "next": 0,
                                "object": 0x711000,
                                "name": "tmp",
                                "stack_offset": -4,
                                "type": 0x712000,
                                "size": 4,
                            }
                        ],
                    },
                    "arguments": {"va": 0x58806C, "head": 0, "objects_sample": []},
                    "temps": {"va": 0x57FEC0, "head": 0, "objects_sample": []},
                    "frame_base_size": {"va": 0x5880CC, "s32": 16},
                    "frame_call_args_size": {"va": 0x58712C, "s32": 8},
                },
            }
        ]
    }

    assert backend_trace_assembler.frame_events_from_map_probe_payload(payload) == [
        {
            "event": "frame_state",
            "source_stage": "final_scheduler",
            "provenance": "backend-map-probe-frame_state",
            "base_size_bytes": 16,
            "call_args_size_bytes": 8,
            "objects": [
                {
                    "area": "locals",
                    "name": "tmp",
                    "stack_offset": -4,
                    "size": 4,
                    "type": "type@0x712000",
                    "confidence": "observed",
                    "provenance": "frame_locals",
                }
            ],
        }
    ]


def _empty_v2_bindings() -> dict[str, object]:
    payload = minimal_object_bindings()
    payload["lifecycle_events"] = []
    payload["objects"] = []
    payload["virtual_bindings"] = []
    payload["frame_bindings"] = []
    payload["coverage"]["objects_seen"] = 0
    payload["coverage"]["virtual_bindings_seen"] = 0
    payload["coverage"]["frame_bindings_seen"] = 0
    payload["coverage"]["lifetime_identity"] = lifetime_coverage(empty=True)
    payload.pop("capture_identity")
    payload.pop("capture_run_id")
    return payload


def _trusted_table() -> dict[str, object]:
    proof = trusted_proof()
    payload = dict(proof.payload)
    return {
        "instrumentation_proof_schema": "mwcc-retro-lifetime-proof.v1",
        "instrumentation_proofs": [
            {
                "compiler_executable_sha256": proof.compiler_executable_sha256,
                "proof_id": proof.proof_id,
                "proof_sha256": proof_sha256(payload),
                "promoted": True,
            }
        ],
        "backend_reader": {
            "pcode_instrumentation": {
                "validated": True,
                "compiler_executable_sha256": proof.compiler_executable_sha256,
                "proof_id": proof.proof_id,
                "proof_sha256": proof.sha256,
                "operand_rewrite_site_ids": ["rewrite-register-operand-1"],
                "operand_mutation_site_ids": ["rewrite-pcode-operands-1"],
                "code_emission_site_ids": ["emit-pcode-1"],
            }
        },
    }


def _base_trace(function: str) -> dict[str, object]:
    payload = json.loads((FIXTURE_ROOT / "backend_trace_v1_minimal.json").read_text())
    payload["source"]["function"] = function
    payload["functions"][0]["name"] = function
    return payload


def test_v2_assembler_recomputes_trust_and_emits_only_independent_capabilities(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.o"
    candidate.write_bytes(_candidate_elf(function="target"))

    result = backend_trace_assembler.assemble_candidate_trace_v2(
        base_trace=_base_trace("target"),
        object_bindings=_empty_v2_bindings(),
        candidate_object=candidate,
        nonce="1" * 32,
        compiler_executable_sha256="a" * 64,
        source_sha256="b" * 64,
        mwcc_command_sha256="c" * 64,
        environment_digest="d" * 64,
        function="target",
        struct_map=_trusted_table(),
    )

    assert result.payload["schema_version"] == backend_schema.SCHEMA_VERSION_V2
    assert result.capabilities == frozenset({"compiler-object-bindings", "pcode-to-code-range"})
    assert result.payload["capabilities"] == [
        "compiler-object-bindings",
        "pcode-to-code-range",
    ]
    assert "object-to-virtual" not in result.payload["capabilities"]
    assert "object-to-frame" not in result.payload["capabilities"]
    identity = result.payload["functions"][0]["object_bindings"]["capture_identity"]
    assert identity["candidate_object_sha256"] == hashlib.sha256(candidate.read_bytes()).hexdigest()
    assert backend_schema.validate_backend_trace(result.payload) == []


def test_v2_assembler_rejects_unpromoted_proof_and_validator_failures(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.o"
    candidate.write_bytes(_candidate_elf(function="target"))
    kwargs = {
        "base_trace": _base_trace("target"),
        "object_bindings": _empty_v2_bindings(),
        "candidate_object": candidate,
        "nonce": "1" * 32,
        "compiler_executable_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "mwcc_command_sha256": "c" * 64,
        "environment_digest": "d" * 64,
        "function": "target",
    }
    table = _trusted_table()
    table["instrumentation_proofs"] = []
    with pytest.raises(ValueError, match="no promoted instrumentation proof"):
        backend_trace_assembler.assemble_candidate_trace_v2(**kwargs, struct_map=table)

    bindings = _empty_v2_bindings()
    bindings["coverage"]["status"] = "complete"  # status alone cannot mask a drop
    bindings["coverage"]["lifetime_identity"]["dropped_events"] = 1
    with pytest.raises(ValueError, match="object binding validation failed"):
        backend_trace_assembler.assemble_candidate_trace_v2(
            **{**kwargs, "object_bindings": bindings}, struct_map=_trusted_table()
        )

    recursive = _empty_v2_bindings()
    recursive["objects"].append(recursive)
    with pytest.raises(ValueError, match="object binding validation failed"):
        backend_trace_assembler.assemble_candidate_trace_v2(
            **{**kwargs, "object_bindings": recursive}, struct_map=_trusted_table()
        )


def test_v2_sidecars_require_same_complete_function_attempt(tmp_path: Path) -> None:
    attempt = {
        "capture_attempt_id": "a" * 32,
        "function_identity": {"requested": "target"},
    }
    object_path = tmp_path / "backend-object-events.v1.json"
    pcode_path = tmp_path / "backend-pcode-events.v1.json"
    envelope = {
        "capture_attempt": attempt,
        "capture_status": {"status": "partial", "capabilities": []},
        "events": [],
        "publication_complete": True,
    }
    object_path.write_text(json.dumps({"schema_version": "mwcc-retro-object-events.v1", **envelope}))
    pcode_path.write_text(json.dumps({"schema_version": "mwcc-retro-pcode-events.v1", **envelope}))

    correlated = backend_trace_assembler.load_correlated_v2_sidecars(object_path, pcode_path, function="target")
    assert correlated.capture_attempt_id == "a" * 32

    payload = json.loads(pcode_path.read_text())
    payload["capture_attempt"]["capture_attempt_id"] = "b" * 32
    pcode_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="capture attempt mismatch"):
        backend_trace_assembler.load_correlated_v2_sidecars(object_path, pcode_path, function="target")

    payload["capture_attempt"] = attempt
    payload["publication_complete"] = False
    pcode_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="publication is incomplete"):
        backend_trace_assembler.load_correlated_v2_sidecars(object_path, pcode_path, function="target")

    payload["publication_complete"] = True
    payload["capture_attempt"]["function_identity"] = {"requested": "other"}
    pcode_path.write_text(json.dumps(payload))
    object_payload = json.loads(object_path.read_text())
    object_payload["capture_attempt"] = payload["capture_attempt"]
    object_path.write_text(json.dumps(object_payload))
    with pytest.raises(ValueError, match="does not identify function"):
        backend_trace_assembler.load_correlated_v2_sidecars(object_path, pcode_path, function="target")


def test_frame_events_from_map_probe_payload_rejects_incomplete_probe_frame() -> None:
    payload = {
        "events": [
            {
                "stage": "final_scheduler",
                "frame_state": {
                    "locals": {"va": 0x587FB8, "objects_sample": []},
                    "frame_base_size": {"va": 0x5880CC, "error": "bad read"},
                    "frame_call_args_size": {"va": 0x58712C, "s32": 8},
                },
            }
        ]
    }

    with pytest.raises(ValueError, match="missing frame_base_size"):
        backend_trace_assembler.frame_events_from_map_probe_payload(payload)


def test_frame_events_from_map_probe_payload_names_unnamed_slots_by_area_and_offset() -> None:
    payload = {
        "events": [
            {
                "stage": "final_scheduler",
                "frame_state": {
                    "arguments": {
                        "va": 0x58806C,
                        "head": 0x710000,
                        "objects_sample": [
                            {
                                "node": 0x710000,
                                "next": 0,
                                "object": 0x711000,
                                "name_ptr": 0,
                                "stack_offset": 4,
                                "type": 0x712000,
                                "size": 4,
                            }
                        ],
                    },
                    "frame_base_size": {"va": 0x5880CC, "s32": 0},
                    "frame_call_args_size": {"va": 0x58712C, "s32": 0},
                },
            }
        ]
    }

    [event] = backend_trace_assembler.frame_events_from_map_probe_payload(payload)

    assert event["objects"][0]["name"] == "arguments_slot_4"
    assert event["objects"][0]["confidence"] == "observed-unnamed"
