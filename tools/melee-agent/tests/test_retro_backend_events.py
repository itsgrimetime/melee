import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import backend_events, backend_schema  # noqa: E402

FIXTURE = REPO / "tools/melee-agent/tests/fixtures/retro/backend_events_v1_minimal.jsonl"
COMPILER = {"family": "MWCC", "version": "GC/1.2.5n", "retail": True}
SOURCE = {
    "tu": "src/melee/test/unit.c",
    "function": "test_fn",
    "mwcc_command_hash": "sha256:events",
}


def test_jsonl_events_normalize_to_backend_trace():
    events = backend_events.load_events(FIXTURE)
    trace = backend_events.normalize_events(
        events,
        compiler=COMPILER,
        source=SOURCE,
        tool_version="test",
    )

    fn = trace["functions"][0]
    cls = fn["regalloc"]["classes"][0]
    node_by_id = {node["ig_id"]: node for node in cls["nodes"]}
    decision_by_id = {decision["id"]: decision for decision in cls["color_decisions"]}

    assert trace["schema_version"] == backend_schema.SCHEMA_VERSION
    assert trace["struct_map"]["schema_version"] == backend_schema.STRUCT_MAP_SCHEMA_VERSION
    assert fn["name"] == "test_fn"
    assert [node["ig_id"] for node in cls["nodes"]] == [32, 33, 40]
    assert cls["edges"] == [
        {
            "a": 32,
            "b": 33,
            "kind": "interference",
            "confidence": "observed",
            "provenance": "interferencegraph",
        }
    ]
    assert cls["coalesce"]["mappings"][0]["alias"] == 40
    assert cls["coalesce"]["mappings"][0]["root"] == 32
    assert cls["simplify_order"] == [33, 32]
    assert cls["select_order"] == [33, 32]
    assert node_by_id[40]["color_status"] == "coalesced_alias"
    assert node_by_id[40]["coalesced_into"] == 32
    assert decision_by_id["gpr-c0"]["blocked_candidates"][0]["holder_ig_id"] == 33
    assert backend_schema.validate_backend_trace(trace) == []


def test_allocator_event_before_regclass_is_rejected():
    events = backend_events.load_events(FIXTURE)
    regclass_index = next(i for i, event in enumerate(events) if event["event"] == "regclass")
    node_index = next(i for i, event in enumerate(events) if event["event"] == "node")
    events[regclass_index], events[node_index] = events[node_index], events[regclass_index]

    with pytest.raises(ValueError, match="regclass must precede node"):
        backend_events.normalize_events(
            events,
            compiler=COMPILER,
            source=SOURCE,
            tool_version="test",
        )
