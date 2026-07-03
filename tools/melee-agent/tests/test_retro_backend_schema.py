import json
import sys
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


def test_regalloc_must_be_object():
    data = json.loads(FIXTURE.read_text())
    data["functions"][0]["regalloc"] = "regalloc"
    errors = backend_schema.validate_backend_trace(data)
    assert any("function test_fn regalloc must be object" in e for e in errors)


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
    errors = backend_schema.validate_backend_trace(data)
    assert any("color decision gpr-c0 missing blocked_candidates" in e for e in errors)


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
