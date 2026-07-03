from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from src.mwcc_debug.pressure_explorer.models import (
    AllocatorClassFacts,
    AllocatorFacts,
    AllocatorNode,
    BlockedCandidate,
    ColorDecision,
    CoalesceFacts,
    FirstDefSite,
    FunctionFacts,
    FunctionFreshness,
    InterferenceEdge,
    LiveFacts,
    RegisterFacts,
    SourceAttributionFact,
    SpillFacts,
    TargetSet,
)
from src.mwcc_debug.pressure_explorer.targets import (
    parse_force_phys_spec,
    parse_target_file,
)


def test_parse_force_phys_spec_supports_class_prefixes() -> None:
    target = parse_force_phys_spec("53:25,0:50:22,f40:14", default_class_id=0)

    assert target.function is None
    assert [(t.class_id, t.ig_id, t.expected_phys) for t in target.targets] == [
        (0, 53, 25),
        (0, 50, 22),
        (1, 40, 14),
    ]
    assert target.protected_ig_ids_by_class() == {0: {53, 50}, 1: {40}}


def test_parse_target_file_json(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "target.json"
    path.write_text(
        json.dumps(
            {
                "function": "fn_80000000",
                "class_id": 0,
                "force_phys": {"37": 25, "40": 26},
                "provenance": {"kind": "unit-test"},
            }
        )
    )

    target = parse_target_file(path)

    assert target.function == "fn_80000000"
    assert [(t.class_id, t.ig_id, t.expected_phys) for t in target.targets] == [
        (0, 37, 25),
        (0, 40, 26),
    ]
    assert target.provenance == {"kind": "unit-test"}


def test_parse_target_file_defaults_provenance_to_path(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "target.json"
    path.write_text(json.dumps({"force_phys": {"37": 25}}))

    target = parse_target_file(path)

    assert target.provenance == {"path": str(path)}


@pytest.mark.parametrize("key", ["force_phys", "virtuals"])
def test_parse_target_file_rejects_empty_target_mapping(
    tmp_path: pathlib.Path,
    key: str,
) -> None:
    path = tmp_path / "target.json"
    path.write_text(json.dumps({key: {}}))

    with pytest.raises(ValueError, match="empty target mapping"):
        parse_target_file(path)


def test_parse_target_file_uses_class_fallback(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "target.json"
    path.write_text(json.dumps({"class": 1, "force_phys": {"37": 25}}))

    target = parse_target_file(path)

    assert [(t.class_id, t.ig_id, t.expected_phys) for t in target.targets] == [
        (1, 37, 25),
    ]


def test_target_set_to_dict_converts_path_values() -> None:
    payload = TargetSet(provenance={"path": pathlib.Path("x")}).to_dict()

    assert json.loads(json.dumps(payload))["provenance"]["path"] == "x"


def test_parse_force_phys_rejects_bad_entry() -> None:
    with pytest.raises(ValueError, match="bad force-phys entry"):
        parse_force_phys_spec("37", default_class_id=0)


def test_allocator_facts_schema_preserves_normalized_shape() -> None:
    decision = ColorDecision(
        id="gpr-c0",
        ig_id=53,
        iter=7,
        assigned_phys=25,
        available_phys_ordered=(25, 26, 27),
        blocked_candidates=(
            BlockedCandidate(
                phys=26,
                holder_ig_id=40,
                holder_assigned_phys=26,
                reason="interference",
            ),
        ),
        candidate_phys_ordered=(25, 26),
        chosen_source="nonvolatile",
        decision_rule="first-available",
        tie_rule="pool-order",
        confidence="observed",
        nonvolatile_pool_before={"available": (25, 26), "reserved": (31,)},
    )
    default_decision = ColorDecision(
        id="gpr-c1",
        ig_id=54,
        iter=8,
        assigned_phys=26,
        available_phys_ordered=(25, 26, 27),
        blocked_candidates=(),
        candidate_phys_ordered=(26, 27),
        chosen_source="nonvolatile",
        decision_rule="first-available",
        tie_rule="pool-order",
        confidence="observed",
    )
    node = AllocatorNode(
        ig_id=53,
        virtual_kind="gpr",
        virtual_number=53,
        color_status="colored",
        coalesced_into=None,
        color_decision_ref="gpr-c0",
        first_def=FirstDefSite(
            pass_id="color",
            block_id="bb0",
            instruction_id="i0",
            opcode="lwz",
            operands="r3, 0(r4)",
            normalized="load",
        ),
        source_attribution=SourceAttributionFact(
            status="available",
            symbol="local_a",
            confidence="observed",
        ),
        live=LiveFacts(blocks=("bb0",), intervals=((0, 3),)),
        degree=3,
        flags=("live",),
        coalesce=CoalesceFacts(root_ig_id=53, aliases=(33,)),
        simplify_order=2,
        select_order=1,
        assigned_phys=25,
        spill=SpillFacts(spilled=False),
    )
    cls = AllocatorClassFacts(
        class_id=0,
        class_name="gpr",
        registers=RegisterFacts(
            physical_count=32,
            allocatable=(3, 4, 25, 26),
            initial_volatile=(3, 4),
            nonvolatile_dispense_order=(31, 30, 29, 28, 27, 26, 25),
            reserved=(0, 1, 2),
            fixed=({"kind": "arg", "phys": 3, "ig_id": 10},),
        ),
        nodes=(node,),
        coalesce={"mappings": [{"alias": 33, "root": 32}]},
        color_decisions=(decision, default_decision),
    )
    facts = AllocatorFacts(
        schema_version="lifetime-pressure-v1",
        producer={"kind": "unit-test"},
        function=FunctionFacts(
            name="fn_80000000",
            source_path="src/melee/test.c",
            freshness=FunctionFreshness(
                status="fresh",
                pcdump_mtime=100,
                source_mtime=90,
            ),
        ),
        classes=(cls,),
        adapter_specific={"0": {"note": "preserved"}},
    )

    assert facts.class_by_id()[0] is cls
    assert cls.node_by_ig()[53] is node
    assert cls.decision_by_ig()[53] is decision
    assert cls.nodes[0].color_decision_ref == "gpr-c0"
    assert isinstance(cls.registers.fixed[0], dict)
    assert cls.non_allocatable_state == {}
    assert default_decision.nonvolatile_pool_before == {}
    assert InterferenceEdge(a=53, b=40).kind == "interference"
    assert InterferenceEdge(a=53, b=40).confidence == "observed"
    assert LiveFacts().confidence == "observed"
    source_attribution = SourceAttributionFact(status="unavailable")
    assert source_attribution.confidence == "unavailable"
    assert source_attribution.compiler_temp is False

    data = facts.to_dict()

    assert data["producer"]["kind"] == "unit-test"
    assert data["classes"][0]["coalesce"]["mappings"][0] == {
        "alias": 33,
        "root": 32,
    }
    assert data["classes"][0]["non_allocatable_state"] == {}
    assert data["classes"][0]["nodes"][0]["flags"] == ["live"]
    assert data["classes"][0]["registers"]["fixed"][0] == {
        "ig_id": 10,
        "kind": "arg",
        "phys": 3,
    }
    assert data["classes"][0]["color_decisions"][0]["nonvolatile_pool_before"] == {
        "available": [25, 26],
        "reserved": [31],
    }
    assert data["classes"][0]["color_decisions"][1]["nonvolatile_pool_before"] == {}
