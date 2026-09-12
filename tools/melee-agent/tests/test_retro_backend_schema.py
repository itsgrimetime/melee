import json
import sys
import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json"


def test_minimal_backend_trace_fixture_validates():
    data = json.loads(FIXTURE.read_text())
    errors = backend_schema.validate_backend_trace(data)
    assert errors == []


def test_schema_dispatch_preserves_v1_and_rejects_unknown_or_hostile_payloads() -> None:
    data = json.loads(FIXTURE.read_text())
    assert backend_schema.SCHEMA_VERSION == backend_schema.SCHEMA_VERSION_V1
    assert backend_schema.validate_backend_trace(data) == []

    data["schema_version"] = "mwcc-retro-backend-trace.v3"
    assert backend_schema.validate_backend_trace(data) == [
        "unsupported backend trace schema 'mwcc-retro-backend-trace.v3'"
    ]
    assert backend_schema.validate_backend_trace([]) == ["backend trace must be an object"]


def test_v2_schema_is_closed_and_phase1_source_fields_are_empty() -> None:
    data = json.loads(FIXTURE.read_text())
    data["schema_version"] = backend_schema.SCHEMA_VERSION_V2
    data["capabilities"] = []
    data["functions"][0]["object_bindings"] = {
        "schema_version": "mwcc-retro-object-bindings.v1",
        "capture_identity": {},
        "capture_run_id": "f" * 64,
        "lifetime_proof": {},
        "coverage": {},
        "lifecycle_events": [],
        "objects": [],
        "virtual_bindings": [],
        "frame_bindings": [],
        "pcode_instructions": [],
        "pcode_occurrences": [],
        "pcode_operand_lineage_events": [],
        "source_bindings": [],
        "source_capture": None,
    }

    errors = backend_schema.validate_backend_trace(data)
    assert not any("unexpected" in error for error in errors)

    data["unexpected"] = True
    data["functions"][0]["object_bindings"]["source_bindings"] = [{}]
    errors = backend_schema.validate_backend_trace(data)
    assert "v2 top-level has unexpected fields: ['unexpected']" in errors
    assert "function test_fn source_bindings must be empty in Phase 1" in errors


def test_v2_capture_identity_is_closed_and_run_scoped() -> None:
    data = json.loads(FIXTURE.read_text())
    data["schema_version"] = backend_schema.SCHEMA_VERSION_V2
    data["capabilities"] = ["object-to-source"]
    identity = {
        "nonce": "1" * 32,
        "compiler_executable_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "mwcc_command_sha256": "c" * 64,
        "environment_digest": "d" * 64,
        "candidate_object_sha256": "e" * 64,
        "function": "test_fn",
        "capture_run_id": "f" * 64,
        "unexpected": True,
    }
    data["functions"][0]["object_bindings"] = {
        "schema_version": "mwcc-retro-object-bindings.v1",
        "capture_identity": identity,
        "capture_run_id": "0" * 64,
        "lifetime_proof": {},
        "coverage": {},
        "lifecycle_events": [],
        "objects": [],
        "virtual_bindings": [],
        "frame_bindings": [],
        "pcode_instructions": [],
        "pcode_occurrences": [],
        "pcode_operand_lineage_events": [],
        "source_bindings": [],
        "source_capture": None,
    }

    errors = backend_schema.validate_backend_trace(data)

    assert any("capture_identity has unexpected fields" in error for error in errors)
    assert any("capture_run_id must equal capture_identity" in error for error in errors)
    assert any("object-to-source" in error for error in errors)


def test_compiler_family_must_be_mwcc():
    data = json.loads(FIXTURE.read_text())
    data["compiler"]["family"] = "Not MWCC"
    errors = backend_schema.validate_backend_trace(data)
    assert any("compiler must describe retail MWCC GC/1.2.5n" in e for e in errors)


def test_compiler_must_be_object():
    data = json.loads(FIXTURE.read_text())
    data["compiler"] = "MWCC GC/1.2.5n"
    errors = backend_schema.validate_backend_trace(data)
    assert any("compiler must be object" in e for e in errors)


def test_source_requires_mwcc_command_and_matching_hash():
    data = json.loads(FIXTURE.read_text())
    source = data["source"]
    command = source["mwcc_command"]
    assert source["mwcc_command_hash"] == (
        "sha256:" + hashlib.sha256(command.encode()).hexdigest()
    )

    source.pop("mwcc_command")
    errors = backend_schema.validate_backend_trace(data)
    assert any("source missing mwcc_command" in e for e in errors)

    source["mwcc_command"] = command
    source["mwcc_command_hash"] = "sha256:bad"
    errors = backend_schema.validate_backend_trace(data)
    assert any("source mwcc_command_hash does not match mwcc_command" in e for e in errors)


def test_regalloc_must_be_object():
    data = json.loads(FIXTURE.read_text())
    data["functions"][0]["regalloc"] = "regalloc"
    errors = backend_schema.validate_backend_trace(data)
    assert any("function test_fn regalloc must be object" in e for e in errors)


def test_frame_map_is_required_and_validated():
    data = json.loads(FIXTURE.read_text())
    frame = data["functions"][0].pop("frame")
    errors = backend_schema.validate_backend_trace(data)
    assert any("function test_fn missing frame" in e for e in errors)

    data = json.loads(FIXTURE.read_text())
    frame = data["functions"][0]["frame"]
    frame["base_size_bytes"] = -1
    frame["objects"][0]["area"] = "unknown"
    frame["objects"][0].pop("stack_offset")
    frame["objects"].append("bad")
    errors = backend_schema.validate_backend_trace(data)
    assert any("frame base_size_bytes must be non-negative int" in e for e in errors)
    assert any("frame object[0] invalid area 'unknown'" in e for e in errors)
    assert any("frame object[0] missing stack_offset" in e for e in errors)
    assert any("frame object[2] must be object" in e for e in errors)

    assert frame


def test_colored_node_without_decision_is_invalid():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls["nodes"][0]["color_decision_ref"] = None
    errors = backend_schema.validate_backend_trace(data)
    assert any("colored node 32 missing color_decision_ref" in e for e in errors)


def test_colored_node_decision_assigned_phys_must_match():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision["assigned_phys"] = 29
    errors = backend_schema.validate_backend_trace(data)
    assert any(
        "colored node 32 assigned_phys 31 does not match decision gpr-c0 assigned_phys 29" in e
        for e in errors
    )


def test_colored_node_requires_assigned_phys():
    data = json.loads(FIXTURE.read_text())
    node = data["functions"][0]["regalloc"]["classes"][0]["nodes"][0]
    node["assigned_phys"] = None
    errors = backend_schema.validate_backend_trace(data)
    assert any("colored node 32 missing assigned_phys" in e for e in errors)


def test_precolored_node_requires_assigned_phys():
    data = json.loads(FIXTURE.read_text())
    node = data["functions"][0]["regalloc"]["classes"][0]["nodes"][0]
    node["color_status"] = "precolored"
    node["assigned_phys"] = None
    node["color_decision_ref"] = None
    errors = backend_schema.validate_backend_trace(data)
    assert any("precolored node 32 missing assigned_phys" in e for e in errors)


def test_selected_uncolored_node_is_invalid():
    data = json.loads(FIXTURE.read_text())
    node = data["functions"][0]["regalloc"]["classes"][0]["nodes"][0]
    node["color_status"] = "uncolored"
    node["assigned_phys"] = None
    node["color_decision_ref"] = None
    errors = backend_schema.validate_backend_trace(data)
    assert any("selected node 32 remains uncolored" in e for e in errors)


def test_spilled_node_requires_spill_decision_and_no_assigned_phys():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    node = cls["nodes"][1]
    decision = cls["color_decisions"][1]
    node["color_status"] = "spilled"
    node["assigned_phys"] = None
    node["spill"] = {"spilled": True, "reason": "no_available_color"}
    decision["assigned_phys"] = None
    decision["available_phys_ordered"] = []
    decision["candidate_phys_ordered"] = []
    decision["chosen_source"] = "spill"
    decision["tie_rule"] = "none_spill"
    decision["decision_rule"] = "spill_no_available_color"
    decision["spill"] = {"spilled": True, "reason": "no_available_color"}

    assert backend_schema.validate_backend_trace(data) == []

    node["color_decision_ref"] = None
    errors = backend_schema.validate_backend_trace(data)
    assert any("spilled node 33 missing color_decision_ref" in e for e in errors)

    node["color_decision_ref"] = "gpr-c1"
    node["assigned_phys"] = 30
    errors = backend_schema.validate_backend_trace(data)
    assert any("spilled node 33 must not have assigned_phys" in e for e in errors)

    node["assigned_phys"] = None
    node["spill"] = {"spilled": False, "reason": None}
    errors = backend_schema.validate_backend_trace(data)
    assert any("spilled node 33 missing spill.spilled true" in e for e in errors)


def test_coalesced_alias_may_have_null_select_and_decision():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    alias = next(n for n in cls["nodes"] if n["ig_id"] == 40)
    assert alias["select_order"] is None
    assert alias["color_decision_ref"] is None
    errors = backend_schema.validate_backend_trace(data)
    assert errors == []


def test_coalesced_alias_must_inherit_root_assigned_phys():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    alias = next(n for n in cls["nodes"] if n["ig_id"] == 40)
    alias["assigned_phys"] = 30
    errors = backend_schema.validate_backend_trace(data)
    assert any(
        "coalesced alias 40 assigned_phys 30 does not match root 32 assigned_phys 31" in e
        for e in errors
    )


def test_color_decision_requires_pressure_fields():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision.pop("blocked_candidates")
    decision.pop("blocked_by")
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision gpr-c0 missing blocked_candidates" in e for e in errors)
    assert any("color decision gpr-c0 missing blocked_by" in e for e in errors)


def test_full_schema_rejects_partial_post_colorgraph_decision():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision.update(
        {
            "node_state_before_select": {
                "status": "unavailable",
                "reason": "retail-post-colorgraph-only",
            },
            "available_phys_ordered": [],
            "candidate_phys_ordered": [31],
            "chosen_source": "observed-retail-assignment",
            "tie_rule": "unavailable-retail-post-colorgraph",
            "decision_rule": "retail-post-colorgraph-observed-assignment",
            "confidence": "observed-partial",
            "provenance": "retail-colorgraph-return",
            "source_stage": "colorgraph_return",
        }
    )
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision gpr-c0 is partial post-colorgraph observation" in e for e in errors)
    assert any("color decision gpr-c0 node_state_before_select missing precolored" in e for e in errors)
    assert any("color decision gpr-c0 available_phys_ordered must be non-empty" in e for e in errors)


def test_color_decision_candidates_must_explain_assigned_phys():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision["candidate_phys_ordered"] = [30]
    errors = backend_schema.validate_backend_trace(data)
    assert any(
        "color decision gpr-c0 candidate_phys_ordered must include assigned_phys 31" in e
        for e in errors
    )


def test_color_decision_blocked_by_requires_holder_and_phys():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision["blocked_by"] = [
        {"ig_id": 99, "phys": 3},
        {"ig_id": 33},
        "bad",
    ]
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision gpr-c0 blocked_by references missing node 99" in e for e in errors)
    assert any("color decision gpr-c0 blocked_by entry missing phys" in e for e in errors)
    assert any("color decision gpr-c0 blocked_by entry must be object" in e for e in errors)


def test_register_metadata_requires_initial_pool_and_boundaries():
    data = json.loads(FIXTURE.read_text())
    regs = data["functions"][0]["regalloc"]["classes"][0]["registers"]
    regs.pop("initial_volatile")
    regs.pop("model_boundary")
    errors = backend_schema.validate_backend_trace(data)
    assert any("registers missing initial_volatile" in e for e in errors)
    assert any("registers missing model_boundary" in e for e in errors)


@pytest.mark.parametrize("field", ["edges", "coalesce", "non_allocatable_state", "simplify_order", "select_order"])
def test_class_level_consumer_fields_are_required(field):
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls.pop(field)
    errors = backend_schema.validate_backend_trace(data)
    assert any(f"gpr missing {field}" in e for e in errors)


def test_duplicate_color_decision_ids_are_invalid():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls["color_decisions"].append(dict(cls["color_decisions"][0]))
    errors = backend_schema.validate_backend_trace(data)
    assert any("duplicate color decision id gpr-c0" in e for e in errors)


def test_color_decision_requires_id_and_provenance():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision.pop("id")
    decision.pop("provenance")
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision missing id" in e for e in errors)
    assert any("color decision <missing-id> missing provenance" in e for e in errors)


def test_color_decision_ig_must_match_colored_node_ref():
    data = json.loads(FIXTURE.read_text())
    decision = data["functions"][0]["regalloc"]["classes"][0]["color_decisions"][0]
    decision["ig_id"] = 99
    errors = backend_schema.validate_backend_trace(data)
    assert any("colored node 32 decision gpr-c0 has ig_id 99" in e for e in errors)


def test_edge_and_coalesce_references_must_exist():
    data = json.loads(FIXTURE.read_text())
    cls = data["functions"][0]["regalloc"]["classes"][0]
    cls["edges"][0]["b"] = 99
    cls["coalesce"]["mappings"][0]["root"] = 98
    errors = backend_schema.validate_backend_trace(data)
    assert any("edge references missing node 99" in e for e in errors)
    assert any("coalesce mapping references missing root 98" in e for e in errors)


def test_empty_register_metadata_is_invalid():
    data = json.loads(FIXTURE.read_text())
    regs = data["functions"][0]["regalloc"]["classes"][0]["registers"]
    regs["allocatable"] = []
    regs["initial_volatile"] = []
    regs["nonvolatile_dispense_order"] = []
    errors = backend_schema.validate_backend_trace(data)
    assert any("registers allocatable must be non-empty" in e for e in errors)
    assert any("registers initial_volatile must be non-empty" in e for e in errors)
    assert any("registers nonvolatile_dispense_order must be non-empty" in e for e in errors)
