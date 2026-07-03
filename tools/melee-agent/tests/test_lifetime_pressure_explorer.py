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

PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
        mr r41,r40
    AFTER REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r25,12(r3)
        add r26,r25,r4
        mr r27,r26
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 40 1 1 0x00
        2 41 0 0 0x08 SPILLED
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 1 1 0x00
          interferers: 40=r26
        1 40 r26 1 1 0x00
          interferers: 37=r25
        2 41 r27 0 0 0x00
          interferers:
""")

SOURCE = textwrap.dedent("""\
    typedef struct Obj { int xC; } Obj;
    void fn_80000000(Obj* obj, int extra) {
        int temp = obj->xC + extra;
        sink(temp);
    }
""")


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


def test_parse_target_file_null_provenance_defaults_to_path(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "target.json"
    path.write_text(json.dumps({"force_phys": {"37": 25}, "provenance": None}))

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


def test_allocator_facts_from_pcdump_contains_nodes_edges_and_decisions() -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump

    facts = facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        pcdump_path="baseline.pcdump.txt",
        source_text=SOURCE,
        source_path="src/example.c",
        class_filter=(0,),
    )

    cls = facts.class_by_id()[0]
    nodes = cls.node_by_ig()
    decisions = cls.decision_by_ig()

    assert facts.schema_version == "allocator-facts.v1"
    assert facts.producer["kind"] == "mwcc-debug-pcdump"
    assert cls.class_name == "gpr"
    assert sorted((edge.a, edge.b) for edge in cls.edges) == [(37, 40)]
    assert nodes[37].first_def.opcode == "lwz"
    assert nodes[37].source_attribution.status in {
        "attributed",
        "ambiguous",
        "unattributed",
    }
    assert nodes[41].spill.spilled is True
    assert decisions[40].assigned_phys == 26
    assert decisions[40].blocked_candidates
    assert decisions[40].confidence in {"observed", "synthesized"}


def test_backend_trace_fixture_maps_to_allocator_facts() -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_backend_trace

    path = pathlib.Path("tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json")
    if not path.exists():
        pytest.skip("shared retail backend trace fixture has not landed")

    facts = facts_from_backend_trace(path, function="test_fn")
    cls = facts.class_by_id()[0]
    nodes = cls.node_by_ig()
    decisions = {decision.id: decision for decision in cls.color_decisions}
    mappings = cls.coalesce["mappings"]

    assert facts.producer["kind"] == "mwcc-retro-backend-trace"
    assert facts.function.name == "test_fn"
    assert {32, 33, 40}.issubset(nodes)
    assert nodes[32].color_status == "colored"
    assert nodes[33].color_status == "coalesced_alias"
    assert nodes[33].coalesced_into == 32
    assert nodes[33].color_decision_ref == "gpr-c0"
    assert nodes[33].assigned_phys == nodes[32].assigned_phys
    assert nodes[40].color_decision_ref == "gpr-c1"
    assert mappings[0]["alias"] == 33
    assert mappings[0]["root"] == 32
    assert "root_phys" in mappings[0]
    assert decisions["gpr-c0"].id == "gpr-c0"
    assert decisions["gpr-c0"].provenance == "retail-trace-fixture"
    assert any(
        candidate.holder_ig_id is not None
        and candidate.holder_assigned_phys is not None
        for decision in decisions.values()
        for candidate in decision.blocked_candidates
    )
    assert cls.registers.fixed and isinstance(cls.registers.fixed[0], dict)
    assert cls.registers.precolored and isinstance(cls.registers.precolored[0], dict)
    assert cls.registers.model_boundary and isinstance(
        cls.registers.model_boundary[0],
        dict,
    )


def test_backend_trace_array_contract_maps_to_allocator_facts(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_backend_trace

    path = tmp_path / "backend_trace_v1_minimal.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "backend-trace.v1",
                "functions": [
                    {
                        "name": "other_fn",
                        "regalloc": {"classes": []},
                    },
                    {
                        "name": "test_fn",
                        "source_path": "src/test.c",
                        "regalloc": {
                            "classes": [
                                {
                                    "class_id": 0,
                                    "class_name": "gpr",
                                    "registers": {
                                        "physical_count": 32,
                                        "allocatable": [3, 4, 31],
                                        "initial_volatile": [3, 4],
                                        "nonvolatile_dispense_order": [31],
                                        "reserved": [1, 2],
                                        "fixed": [{"phys": 1, "name": "sp"}],
                                        "precolored": [{"ig_id": 3, "phys": 3}],
                                        "model_boundary": [{"phys": 0, "name": "r0"}],
                                    },
                                    "nodes": [
                                        {
                                            "ig_id": 32,
                                            "virtual": {"kind": "r", "number": 32},
                                            "color_status": "colored",
                                            "coalesced_into": None,
                                            "color_decision_ref": "gpr-c0",
                                            "first_def": {
                                                "pass_id": "select",
                                                "block_id": "bb0",
                                                "instruction_id": "i0",
                                                "opcode": "lwz",
                                                "operands": "r32,0(r3)",
                                                "normalized": "load",
                                            },
                                            "source_attribution": {
                                                "status": "attributed",
                                                "symbol": "root",
                                                "confidence": "observed",
                                            },
                                            "live": {
                                                "blocks": ["bb0"],
                                                "intervals": [[0, 2]],
                                                "confidence": "observed",
                                            },
                                            "degree": 1,
                                            "flags": ["live"],
                                            "coalesce": {
                                                "root_ig_id": 32,
                                                "aliases": [33],
                                            },
                                            "simplify_order": 0,
                                            "select_order": 0,
                                            "assigned_phys": 31,
                                            "spill": {"spilled": False},
                                        },
                                        {
                                            "ig_id": 33,
                                            "virtual": {"kind": "r", "number": 33},
                                            "color_status": "coalesced_alias",
                                            "coalesced_into": 32,
                                            "color_decision_ref": "gpr-c0",
                                            "first_def": {
                                                "pass_id": "coalesce",
                                                "block_id": "bb0",
                                                "instruction_id": "i1",
                                                "opcode": "mr",
                                                "operands": "r33,r32",
                                                "normalized": "copy",
                                            },
                                            "source_attribution": {
                                                "status": "unattributed",
                                                "confidence": "unavailable",
                                            },
                                            "live": {
                                                "blocks": ["bb0"],
                                                "intervals": [[1, 2]],
                                                "confidence": "observed",
                                            },
                                            "degree": 0,
                                            "flags": [],
                                            "coalesce": {
                                                "root_ig_id": 32,
                                                "aliases": [],
                                            },
                                            "simplify_order": 1,
                                            "select_order": None,
                                            "assigned_phys": None,
                                            "spill": {"spilled": False},
                                        },
                                        {
                                            "ig_id": 40,
                                            "virtual": {"kind": "r", "number": 40},
                                            "color_status": "colored",
                                            "coalesced_into": None,
                                            "color_decision_ref": "gpr-c1",
                                            "first_def": {
                                                "pass_id": "select",
                                                "block_id": "bb0",
                                                "instruction_id": "i2",
                                                "opcode": "add",
                                                "operands": "r40,r32,r4",
                                            },
                                            "source_attribution": {
                                                "status": "attributed",
                                                "symbol": "sum",
                                                "confidence": "observed",
                                            },
                                            "live": {
                                                "blocks": ["bb0"],
                                                "intervals": [[2, 3]],
                                                "confidence": "observed",
                                            },
                                            "degree": 1,
                                            "flags": [],
                                            "coalesce": {
                                                "root_ig_id": 40,
                                                "aliases": [],
                                            },
                                            "simplify_order": 2,
                                            "select_order": 1,
                                            "assigned_phys": 4,
                                            "spill": {"spilled": False},
                                        },
                                    ],
                                    "edges": [
                                        {
                                            "a": 32,
                                            "b": 40,
                                            "kind": "interference",
                                            "confidence": "observed",
                                        }
                                    ],
                                    "coalesce": {
                                        "mappings": [
                                            {
                                                "alias": 33,
                                                "root": 32,
                                                "root_phys": 31,
                                            }
                                        ]
                                    },
                                    "coalesce_mappings": [[33, 32]],
                                    "non_allocatable_state": {"reserved": [1, 2]},
                                    "simplify_order": [32, 33, 40],
                                    "select_order": [32, 40],
                                    "color_decisions": [
                                        {
                                            "id": "gpr-c0",
                                            "ig_id": 32,
                                            "iter": 0,
                                            "assigned_phys": 31,
                                            "available_phys_ordered": [3, 4, 31],
                                            "blocked_candidates": [
                                                {
                                                    "phys": 4,
                                                    "holder_ig_id": 40,
                                                    "holder_assigned_phys": 4,
                                                    "reason": "interference",
                                                }
                                            ],
                                            "candidate_phys_ordered": [31],
                                            "chosen_source": "nonvolatile",
                                            "decision_rule": "retail",
                                            "tie_rule": "fixture",
                                            "confidence": "observed",
                                            "provenance": "retail-trace-fixture",
                                            "blocked_by": [
                                                {"ig_id": 40, "phys": 4}
                                            ],
                                            "node_state_before_select": {"degree": 1},
                                            "volatile_pool_before": [3, 4],
                                            "nonvolatile_pool_before": {
                                                "available": [31]
                                            },
                                            "reserved_or_precolored_filtered": [1, 2],
                                        },
                                        {
                                            "id": "gpr-c1",
                                            "ig_id": 40,
                                            "iter": 1,
                                            "assigned_phys": 4,
                                            "available_phys_ordered": [3, 4, 31],
                                            "blocked_candidates": [],
                                            "candidate_phys_ordered": [4, 31],
                                            "chosen_source": "volatile",
                                            "decision_rule": "retail",
                                            "tie_rule": "fixture",
                                            "confidence": "observed",
                                            "provenance": "retail-trace-fixture",
                                        },
                                    ],
                                }
                            ]
                        },
                    },
                ],
            }
        )
    )

    facts = facts_from_backend_trace(path, function="test_fn")
    cls = facts.class_by_id()[0]
    nodes = cls.node_by_ig()
    decisions = {decision.id: decision for decision in cls.color_decisions}
    mappings = cls.coalesce["mappings"]

    assert facts.function.name == "test_fn"
    assert 0 in facts.class_by_id()
    assert {32, 33, 40}.issubset(nodes)
    assert nodes[32].color_status == "colored"
    assert nodes[33].color_status == "coalesced_alias"
    assert nodes[33].coalesced_into == 32
    assert nodes[33].color_decision_ref == "gpr-c0"
    assert nodes[33].assigned_phys == nodes[32].assigned_phys
    assert nodes[40].color_decision_ref == "gpr-c1"
    assert mappings[0]["alias"] == 33
    assert mappings[0]["root"] == 32
    assert "root_phys" in mappings[0]
    assert "gpr-c0" in decisions
    assert any(
        candidate.holder_ig_id is not None
        and candidate.holder_assigned_phys is not None
        for decision in decisions.values()
        for candidate in decision.blocked_candidates
    )
    assert cls.registers.fixed and isinstance(cls.registers.fixed[0], dict)
    assert cls.registers.precolored and isinstance(cls.registers.precolored[0], dict)
    assert cls.registers.model_boundary and isinstance(
        cls.registers.model_boundary[0],
        dict,
    )


def test_allocator_facts_from_real_pcdump_has_allocator_shape() -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump

    fixture = pathlib.Path(
        "tools/melee-agent/tests/fixtures/mwcc_debug/lbDvd_80018A2C_pcdump.txt"
    )
    if not fixture.exists():
        pytest.skip("lbDvd pcdump fixture missing")

    facts = facts_from_pcdump(
        fixture.read_text(),
        "lbDvd_80018A2C",
        pcdump_path=fixture,
        class_filter=(0,),
    )
    cls = facts.class_by_id()[0]

    assert cls.nodes
    assert cls.color_decisions
    assert cls.simplify_order
    assert cls.select_order
    assert cls.edges or cls.coalesce_mappings or any(
        node.spill.spilled for node in cls.nodes
    )
