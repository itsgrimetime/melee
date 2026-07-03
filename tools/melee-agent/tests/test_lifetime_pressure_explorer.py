from __future__ import annotations

import copy
import json
import pathlib
import re
import textwrap
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.mwcc_debug.pressure_explorer.models import (
    AllocatorClassFacts,
    AllocatorFacts,
    AllocatorNode,
    Blocker,
    BlockedCandidate,
    ColorDecision,
    CoalesceFacts,
    FirstDefSite,
    FunctionFacts,
    FunctionFreshness,
    InterferenceEdge,
    LifetimePressureReport,
    LiveFacts,
    RegisterFacts,
    SourceAttributionFact,
    SpillFacts,
    TargetSet,
    TargetPressureReport,
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

CANDIDATE_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    AFTER REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r26,12(r3)
        add r25,r26,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r26 1 1 0x00
          interferers: 40=r25
        1 40 r25 1 1 0x00
          interferers: 37=r26
""")

SOURCE = textwrap.dedent("""\
    typedef struct Obj { int xC; } Obj;
    void fn_80000000(Obj* obj, int extra) {
        int temp = obj->xC + extra;
        sink(temp);
    }
""")


def _parsed_pressure_facts() -> AllocatorFacts:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump

    return facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        source_text=SOURCE,
        class_filter=(0,),
    )


def _source_attr(symbol: str = "local") -> SourceAttributionFact:
    return SourceAttributionFact(status="attributed", symbol=symbol, confidence="observed")


def _manual_node(
    ig_id: int,
    *,
    assigned_phys: int | None,
    color_status: str = "colored",
    coalesced_into: int | None = None,
    coalesce: CoalesceFacts | None = None,
    select_order: int | None = 0,
) -> AllocatorNode:
    return AllocatorNode(
        ig_id=ig_id,
        virtual_kind="gpr",
        virtual_number=ig_id,
        color_status=color_status,
        coalesced_into=coalesced_into,
        color_decision_ref=f"gpr-c{ig_id}",
        first_def=FirstDefSite(opcode="mr", operands=f"r{ig_id}, r3"),
        source_attribution=_source_attr(f"v{ig_id}"),
        live=LiveFacts(blocks=("B0",), intervals=((0, 1),)),
        degree=0,
        flags=(),
        coalesce=coalesce or CoalesceFacts(root_ig_id=ig_id),
        simplify_order=0,
        select_order=select_order,
        assigned_phys=assigned_phys,
        spill=SpillFacts(spilled=False),
    )


def _manual_decision(
    ig_id: int,
    *,
    assigned_phys: int | None,
    candidate_phys_ordered: tuple[int, ...] = (25, 26, 27),
    chosen_source: str = "observed",
    confidence: str = "observed",
) -> ColorDecision:
    return ColorDecision(
        id=f"gpr-c{ig_id}",
        ig_id=ig_id,
        iter=0,
        assigned_phys=assigned_phys,
        available_phys_ordered=(25, 26, 27),
        blocked_candidates=(),
        candidate_phys_ordered=candidate_phys_ordered,
        chosen_source=chosen_source,
        decision_rule="unit-test",
        tie_rule="unit-test",
        confidence=confidence,
    )


def _manual_facts(
    *,
    nodes: tuple[AllocatorNode, ...],
    decisions: tuple[ColorDecision, ...],
    edges: tuple[InterferenceEdge, ...] = (),
    coalesce_mappings: tuple[tuple[int, int], ...] = (),
) -> AllocatorFacts:
    return AllocatorFacts(
        schema_version="allocator-facts.v1",
        producer={"kind": "unit-test"},
        function=FunctionFacts(
            name="fn_80000000",
            source_path=None,
            freshness=FunctionFreshness(status="fresh"),
        ),
        classes=(
            AllocatorClassFacts(
                class_id=0,
                class_name="gpr",
                registers=RegisterFacts(physical_count=32, allocatable=(25, 26, 27)),
                nodes=nodes,
                edges=edges,
                coalesce={
                    "mappings": [
                        {"alias": alias, "root": root}
                        for alias, root in coalesce_mappings
                    ]
                },
                coalesce_mappings=coalesce_mappings,
                color_decisions=decisions,
            ),
        ),
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


def test_candidate_models_reexport_from_pressure_explorer_package() -> None:
    from src.mwcc_debug.pressure_explorer import CandidateComparison, CandidateSpec

    spec = CandidateSpec(label="candidate", path="candidate.pcdump.txt", kind="pcdump")
    comparison = CandidateComparison(
        label="candidate",
        path="candidate.pcdump.txt",
        status="rejected",
        target_results={},
        pressure_delta={},
        identity_status="trusted",
    )

    assert spec.kind == "pcdump"
    assert comparison.identity_status == "trusted"


def test_candidate_comparison_rejects_protected_target_regression(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    base_path = tmp_path / "base.pcdump.txt"
    cand_path = tmp_path / "candidate.pcdump.txt"
    base_path.write_text(PCDUMP)
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(PCDUMP, "fn_80000000", pcdump_path=base_path, source_text=SOURCE, class_filter=(0,))
    target = parse_force_phys_spec("40:25,37:25")

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("swap", cand_path)],
        source_text=SOURCE,
    )[0]

    assert comparison.label == "swap"
    assert comparison.status == "rejected"
    assert comparison.target_results[40]["satisfied"] is True
    assert comparison.target_results[37]["regressed"] is True


def test_candidate_comparison_reports_full_target_match(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    cand_path = tmp_path / "candidate.pcdump.txt"
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(PCDUMP, "fn_80000000", source_text=SOURCE, class_filter=(0,))
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("hit", cand_path)],
        source_text=SOURCE,
    )[0]

    assert comparison.status == "full_target_match"
    assert comparison.target_results[40]["satisfied"] is True
    assert comparison.target_results[40]["improved"] is True


@pytest.mark.parametrize(
    ("guard_name", "expected_warning"),
    [
        ("checkdiff_guard", "checkdiff guard rejected candidate"),
        ("structural_guard", "structural guard rejected candidate"),
    ],
)
def test_candidate_comparison_rejects_guard_failure_evidence(
    tmp_path: pathlib.Path,
    guard_name: str,
    expected_warning: str,
) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    cand_path = tmp_path / "candidate.pcdump.txt"
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(PCDUMP, "fn_80000000", source_text=SOURCE, class_filter=(0,))
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("hit", cand_path)],
        source_text=SOURCE,
        validation_evidence={"hit": {guard_name: {"accepted": False}}},
    )[0]

    assert comparison.status == "rejected"
    assert comparison.target_results[40]["satisfied"] is True
    assert expected_warning in comparison.warnings


def test_candidate_comparison_reports_partial_progress(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    cand_path = tmp_path / "candidate.pcdump.txt"
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(PCDUMP, "fn_80000000", source_text=SOURCE, class_filter=(0,))
    target = parse_force_phys_spec("40:25,37:27", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("partial", cand_path)],
        source_text=SOURCE,
    )[0]

    assert comparison.status == "partial_progress"
    assert comparison.target_results[40]["improved"] is True
    assert comparison.target_results[37]["satisfied"] is False
    assert comparison.target_results[37]["regressed"] is False


def test_candidate_comparison_rejects_untrusted_identity(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    cand_path = tmp_path / "candidate.pcdump.txt"
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(PCDUMP, "fn_80000000", source_text=SOURCE, class_filter=(0,))
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("unsafe", cand_path)],
        source_text=None,
        require_reanchor=True,
    )[0]

    assert comparison.status == "rejected"
    assert comparison.identity_status == "unsafe"
    assert "role reanchor unavailable" in " ".join(comparison.warnings)


def test_candidate_comparison_reanchors_identity_when_source_available(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug import role_descriptor, role_reanchor
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    calls: list[tuple[str, object]] = []

    class StubCompile:
        def __init__(self, text: str, function: str, source: str) -> None:
            self.text = text
            self.function = function
            self.source = source

        @classmethod
        def from_text(cls, text: str, function: str, source: str) -> "StubCompile":
            calls.append(("compile", function))
            return cls(text, function, source)

    def build_target_spec(
        compile_obj: StubCompile,
        force_phys: dict[int, int],
        class_id: int,
        target_kind: str,
        provenance: dict[str, object],
        causal_closure: bool = False,
    ) -> SimpleNamespace:
        calls.append(("target_spec", dict(force_phys)))
        return SimpleNamespace(
            function=compile_obj.function,
            roles=[
                SimpleNamespace(
                    original_ig=ig,
                    desired_phys=phys,
                    class_id=class_id,
                )
                for ig, phys in force_phys.items()
            ],
        )

    def reanchor(
        target_spec: SimpleNamespace,
        new_compile: StubCompile,
        class_id: int = 0,
    ) -> SimpleNamespace:
        calls.append(("reanchor", class_id))
        return SimpleNamespace(
            class_id=class_id,
            force_phys={40: 25},
            diagnostics={},
            matched={40: 40},
        )

    monkeypatch.setattr(role_descriptor, "Compile", StubCompile)
    monkeypatch.setattr(role_descriptor, "build_target_spec", build_target_spec)
    monkeypatch.setattr(role_reanchor, "reanchor", reanchor)

    base_path = tmp_path / "base.pcdump.txt"
    cand_path = tmp_path / "candidate.pcdump.txt"
    base_path.write_text(PCDUMP)
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        pcdump_path=base_path,
        source_text=SOURCE,
        class_filter=(0,),
    )
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("hit", cand_path)],
        source_text=SOURCE,
        require_reanchor=True,
    )[0]

    assert comparison.status == "full_target_match"
    assert comparison.identity_status == "reanchored"
    assert comparison.target_results[40]["satisfied"] is True
    assert ("reanchor", 0) in calls


def test_candidate_comparison_rejects_reanchor_excluded_protected_target(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug import role_descriptor, role_reanchor
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    class StubCompile:
        @classmethod
        def from_text(cls, text: str, function: str, source: str) -> SimpleNamespace:
            return SimpleNamespace(text=text, function=function, source=source)

    def build_target_spec(
        compile_obj: SimpleNamespace,
        force_phys: dict[int, int],
        class_id: int,
        target_kind: str,
        provenance: dict[str, object],
        causal_closure: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(function=compile_obj.function, roles=())

    def reanchor(
        target_spec: SimpleNamespace,
        new_compile: SimpleNamespace,
        class_id: int = 0,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            class_id=class_id,
            force_phys={},
            diagnostics={40: "ambiguous"},
            matched={},
        )

    monkeypatch.setattr(role_descriptor, "Compile", StubCompile)
    monkeypatch.setattr(role_descriptor, "build_target_spec", build_target_spec)
    monkeypatch.setattr(role_reanchor, "reanchor", reanchor)

    base_path = tmp_path / "base.pcdump.txt"
    cand_path = tmp_path / "candidate.pcdump.txt"
    base_path.write_text(PCDUMP)
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        pcdump_path=base_path,
        source_text=SOURCE,
        class_filter=(0,),
    )
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("hit", cand_path)],
        source_text=SOURCE,
        require_reanchor=True,
    )[0]

    assert comparison.status == "rejected"
    assert comparison.identity_status == "unsafe"
    assert comparison.target_results[40]["unsafe"] is True
    assert "reanchor excluded protected target 40: ambiguous" in comparison.warnings


def test_candidate_comparison_rejects_missing_function(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    cand_path = tmp_path / "wrong_function.pcdump.txt"
    cand_path.write_text(CANDIDATE_PCDUMP.replace("fn_80000000", "fn_80000001"))
    baseline = facts_from_pcdump(PCDUMP, "fn_80000000", source_text=SOURCE, class_filter=(0,))
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("missing", cand_path)],
        source_text=SOURCE,
    )[0]

    assert comparison.status == "rejected"
    assert comparison.identity_status == "function_missing"
    assert comparison.target_results[40]["unsafe"] is True


def test_source_candidate_rejected_without_compile_capable_mode(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import parse_candidate_specs

    source = tmp_path / "candidate.c"
    source.write_text("void fn_80000000(void) {}\n")

    with pytest.raises(ValueError, match="source candidate requires compile-capable validation mode"):
        parse_candidate_specs([f"src={source}"], validate_mode="none")

    remote = parse_candidate_specs([f"src={source}"], validate_mode="remote")
    assert remote[0].kind == "source-dry-run"


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


def test_analyze_reports_no_pressure_issue_when_target_matches() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _parsed_pressure_facts()
    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("37:25", default_class_id=0),
    )

    target = report.targets[0]
    assert target.status == "no_pressure_issue"
    assert target.current_phys == 25
    assert target.expected_phys == 25
    assert target.blockers == ()


def test_analyze_finds_expected_phys_holder_blocker() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _parsed_pressure_facts()
    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("40:25", default_class_id=0),
    )

    target = report.targets[0]
    assert target.status == "blocked"
    assert target.current_phys == 26
    assert target.expected_phys == 25
    assert target.blockers[0].kind == "expected_phys_holder"
    assert target.blockers[0].ig_id == 37
    assert "remove interference" in target.must_change[0]


def test_analyze_rejects_target_function_mismatch() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure

    facts = _parsed_pressure_facts()

    with pytest.raises(ValueError, match="target function mismatch"):
        analyze_lifetime_pressure(
            facts,
            TargetSet(
                function="fn_80000004",
                targets=parse_force_phys_spec("37:25", default_class_id=0).targets,
            ),
        )


def test_analyze_reports_missing_class_as_abstained_target() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _parsed_pressure_facts()
    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("f40:14", default_class_id=0),
    )

    assert report.targets[0].status == "abstained"
    assert "requested class 1 missing" in report.warnings


def test_analyze_reports_spilled_target() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _parsed_pressure_facts()
    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("41:25", default_class_id=0),
    )

    assert report.targets[0].status == "spilled"
    assert report.targets[0].spill.spilled is True


def test_analyze_reports_incomplete_allocator_state_blocker() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _parsed_pressure_facts()
    cls = facts.class_by_id()[0]
    decision = cls.decision_by_ig()[40]
    facts = replace(
        facts,
        classes=(
            replace(
                cls,
                edges=(),
                color_decisions=(
                    cls.color_decisions[0],
                    replace(
                        decision,
                        blocked_candidates=(),
                        confidence="synthesized",
                    ),
                    cls.color_decisions[2],
                ),
            ),
        ),
    )

    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("40:25", default_class_id=0),
    )

    assert report.targets[0].status == "blocked"
    assert report.targets[0].blockers[0].kind == "incomplete_allocator_state"


def test_analyze_reports_candidate_order_when_expected_phys_is_later() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _parsed_pressure_facts()
    cls = facts.class_by_id()[0]
    decision = cls.decision_by_ig()[40]
    facts = replace(
        facts,
        classes=(
            replace(
                cls,
                edges=(),
                color_decisions=(
                    cls.color_decisions[0],
                    replace(
                        decision,
                        blocked_candidates=(),
                        candidate_phys_ordered=(26, 25, 27),
                    ),
                    cls.color_decisions[2],
                ),
            ),
        ),
    )

    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("40:25", default_class_id=0),
    )

    target = report.targets[0]
    assert target.status == "blocked"
    assert target.current_phys == 26
    assert any(blocker.kind == "candidate_order" for blocker in target.blockers)


def test_analyze_reports_coalesced_alias_without_shared_fixture() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _manual_facts(
        nodes=(
            _manual_node(
                32,
                assigned_phys=31,
                coalesce=CoalesceFacts(root_ig_id=32, aliases=(33,)),
            ),
            _manual_node(
                33,
                assigned_phys=31,
                color_status="coalesced_alias",
                coalesced_into=32,
                coalesce=CoalesceFacts(root_ig_id=32, aliases=(33,)),
            ),
        ),
        decisions=(_manual_decision(32, assigned_phys=31),),
        coalesce_mappings=((33, 32),),
    )

    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("33:25", default_class_id=0),
    )

    assert report.targets[0].status == "coalesced_away"
    assert report.targets[0].current_phys == 31
    assert report.targets[0].coalesce.root_ig_id == 32


def test_analyze_reports_select_order_fallback_blocker() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = _manual_facts(
        nodes=(_manual_node(40, assigned_phys=26, select_order=7),),
        decisions=(
            _manual_decision(
                40,
                assigned_phys=26,
                candidate_phys_ordered=(25, 26, 27),
                chosen_source="observed",
            ),
        ),
    )

    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("40:25", default_class_id=0),
    )

    target = report.targets[0]
    assert target.status == "blocked"
    assert target.blockers[0].kind == "select_order"
    assert "select" in target.blockers[0].reason


def test_blocker_sort_orders_impact_then_ig_id_with_none_last() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import _sort_blockers

    blockers = _sort_blockers(
        (
            Blocker(40, None, "none-id", None, 50, "none"),
            Blocker(40, 37, "lower-impact", 25, 100, "first"),
            Blocker(40, 41, "same-impact", 26, 50, "same"),
        )
    )

    assert [(blocker.impact, blocker.ig_id) for blocker in blockers] == [
        (100, 37),
        (50, 41),
        (50, None),
    ]


def test_no_target_mode_is_inventory_only() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure

    facts = _parsed_pressure_facts()
    report = analyze_lifetime_pressure(facts, target_set=None)

    assert report.inventory_only is True
    assert report.targets == ()
    assert any("derive a target" in command.command for command in report.validation_commands)
    assert report.hypotheses == ()


def test_hypotheses_rank_lifetime_shortening_for_direct_blocker() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.hypotheses import attach_hypotheses
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        pcdump_path="baseline.pcdump.txt",
        source_text=SOURCE,
        source_path="src/example.c",
        class_filter=(0,),
    )
    report = analyze_lifetime_pressure(facts, parse_force_phys_spec("40:25"))
    enriched = attach_hypotheses(
        report,
        pcdump_path="baseline.pcdump.txt",
        source_path="src/example.c",
        allow_stale_pcdump=False,
    )

    assert enriched.hypotheses
    assert enriched.hypotheses[0].action in {
        "shorten_lifetime",
        "split_or_scope_temp",
        "materialize_expression",
    }
    assert any(
        h.line_mapping_status == "fresh"
        and re.search(r":\d+$", h.source_owner) is not None
        for h in enriched.hypotheses
    )
    commands = {cmd.id: cmd.command for cmd in enriched.validation_commands}
    assert any("debug mutate lifetime-layout" in cmd for cmd in commands.values())
    assert any("debug mutate simplify-order" in cmd for cmd in commands.values())
    assert any("debug target score-source" in cmd for cmd in commands.values())


def test_stale_pcdump_marks_line_specific_hints() -> None:
    from dataclasses import replace

    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.hypotheses import attach_hypotheses
    from src.mwcc_debug.pressure_explorer.models import FunctionFreshness
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        source_text=SOURCE,
        source_path="src/example.c",
        class_filter=(0,),
    )
    stale = replace(
        facts,
        function=replace(
            facts.function,
            freshness=FunctionFreshness(
                status="stale",
                pcdump_mtime=1.0,
                source_mtime=2.0,
            ),
        ),
    )
    report = analyze_lifetime_pressure(stale, parse_force_phys_spec("40:25"))
    enriched = attach_hypotheses(
        report,
        pcdump_path="baseline.pcdump.txt",
        source_path="src/example.c",
        allow_stale_pcdump=True,
    )

    assert enriched.hypotheses
    assert all(
        h.line_mapping_status in {"stale_line_mapping", "not_line_specific"}
        for h in enriched.hypotheses
    )
    assert all(
        re.search(r":\d+$", h.source_owner) is None
        for h in enriched.hypotheses
        if h.line_mapping_status == "stale_line_mapping"
    )


def test_fpr_hypotheses_emit_class_scoped_validation_commands() -> None:
    from src.mwcc_debug.pressure_explorer.hypotheses import attach_hypotheses

    blocker = Blocker(
        target_ig_id=40,
        ig_id=41,
        kind="expected_phys_holder",
        assigned_phys=25,
        impact=100,
        reason="expected phys f25 is held by interfering IG 41",
    )
    target = TargetPressureReport(
        class_id=1,
        ig_id=40,
        virtual={"kind": "fpr", "number": 40},
        current_phys=24,
        expected_phys=25,
        status="blocked",
        first_def=None,
        source_attribution=SourceAttributionFact(
            status="attributed",
            symbol="target",
            line=10,
            confidence="observed",
        ),
        live=LiveFacts(),
        simplify_order=1,
        select_order=1,
        coalesce=CoalesceFacts(root_ig_id=40),
        spill=SpillFacts(spilled=False),
        blockers=(blocker,),
        why_current_color="mwcc-colorgraph selected f24",
        must_change=("remove interference",),
        confidence="observed",
    )
    facts = AllocatorFacts(
        schema_version="allocator-facts.v1",
        producer={"kind": "unit-test"},
        function=FunctionFacts(
            name="fn_80000000",
            source_path="src/example.c",
            freshness=FunctionFreshness(status="fresh"),
        ),
        classes=(
            AllocatorClassFacts(
                class_id=1,
                class_name="fpr",
                registers=RegisterFacts(physical_count=32, allocatable=(24, 25)),
                nodes=(
                    _manual_node(41, assigned_phys=25),
                ),
            ),
        ),
    )
    report = LifetimePressureReport(
        schema_version="lifetime-pressure-report.v1",
        function="fn_80000000",
        inventory_only=False,
        inputs={},
        targets=(target,),
        allocator_facts=facts,
        blockers=(blocker,),
        source_attribution={"status": "not_ranked"},
        hypotheses=(),
        validation_commands=(),
    )

    enriched = attach_hypotheses(
        report,
        pcdump_path="baseline.pcdump.txt",
        source_path="src/example.c",
        allow_stale_pcdump=False,
    )
    commands = {command.id: command.command for command in enriched.validation_commands}
    select_order = commands["select-order-1-40-41"]
    simplify_order = commands["simplify-order-1-40"]
    lifetime_layout = commands["lifetime-layout-1-40-41"]

    assert "--force-phys 1:40:25" in select_order
    assert "--force-phys f40:25" not in select_order
    assert "--force-phys 1:40:25" in simplify_order
    assert "--class 1" in select_order
    assert "--class 1" in simplify_order
    assert "--pairs f40/f41" in lifetime_layout
    assert "--target 'f40<f41'" in select_order


def test_blocker_hypothesis_ids_include_blocker_discriminator() -> None:
    from src.mwcc_debug.pressure_explorer.hypotheses import attach_hypotheses

    blockers = (
        Blocker(40, 41, "expected_phys_holder", 25, 100, "holder 41"),
        Blocker(40, 42, "expected_phys_holder", 25, 100, "holder 42"),
    )
    target = TargetPressureReport(
        class_id=0,
        ig_id=40,
        virtual={"kind": "gpr", "number": 40},
        current_phys=26,
        expected_phys=25,
        status="blocked",
        first_def=None,
        source_attribution=SourceAttributionFact(status="attributed", symbol="target"),
        live=LiveFacts(),
        simplify_order=1,
        select_order=1,
        coalesce=CoalesceFacts(root_ig_id=40),
        spill=SpillFacts(spilled=False),
        blockers=blockers,
        why_current_color="mwcc-colorgraph selected r26",
        must_change=("remove interference",),
        confidence="observed",
    )
    facts = AllocatorFacts(
        schema_version="allocator-facts.v1",
        producer={"kind": "unit-test"},
        function=FunctionFacts(
            name="fn_80000000",
            source_path="src/example.c",
            freshness=FunctionFreshness(status="fresh"),
        ),
        classes=(
            AllocatorClassFacts(
                class_id=0,
                class_name="gpr",
                registers=RegisterFacts(physical_count=32, allocatable=(25, 26)),
                nodes=(
                    _manual_node(41, assigned_phys=25),
                    _manual_node(42, assigned_phys=25),
                ),
            ),
        ),
    )
    report = LifetimePressureReport(
        schema_version="lifetime-pressure-report.v1",
        function="fn_80000000",
        inventory_only=False,
        inputs={},
        targets=(target,),
        allocator_facts=facts,
        blockers=blockers,
        source_attribution={"status": "not_ranked"},
        hypotheses=(),
        validation_commands=(),
    )

    enriched = attach_hypotheses(
        report,
        pcdump_path="baseline.pcdump.txt",
        source_path="src/example.c",
        allow_stale_pcdump=False,
    )
    hypothesis_ids = [hypothesis.id for hypothesis in enriched.hypotheses]

    assert len(hypothesis_ids) == len(set(hypothesis_ids))
    assert any("-41-" in hypothesis_id for hypothesis_id in hypothesis_ids)
    assert any("-42-" in hypothesis_id for hypothesis_id in hypothesis_ids)


def test_coalesced_alias_node_reports_coalesced_away() -> None:
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.facts import facts_from_backend_trace
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    fixture = pathlib.Path("tools/melee-agent/tests/fixtures/retro/backend_trace_v1_minimal.json")
    if not fixture.exists():
        pytest.skip("shared retail backend trace fixture has not landed")

    facts = facts_from_backend_trace(fixture, function="test_fn")
    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("33:31", default_class_id=0),
    )

    assert report.targets[0].status == "coalesced_away"
    assert report.targets[0].current_phys == 31
    assert report.targets[0].coalesce.root_ig_id == 32


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


def _minimal_backend_trace_payload() -> dict:
    return {
        "schema_version": "backend-trace.v1",
        "functions": [
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
                                "reserved": [1, 2],
                                "nonvolatile_dispense_order": [31],
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
                                    "assigned_phys": 31,
                                    "simplify_order": 0,
                                    "select_order": 0,
                                    "first_def": {"opcode": "lwz"},
                                    "source_attribution": {
                                        "status": "attributed",
                                        "confidence": "observed",
                                    },
                                    "live": {"blocks": [], "intervals": []},
                                    "coalesce": {
                                        "root_ig_id": 32,
                                        "aliases": [],
                                    },
                                    "spill": {"spilled": False},
                                }
                            ],
                            "edges": [],
                            "coalesce": {"mappings": []},
                            "non_allocatable_state": {},
                            "simplify_order": [32],
                            "select_order": [32],
                            "color_decisions": [
                                {
                                    "id": "gpr-c0",
                                    "ig_id": 32,
                                    "assigned_phys": 31,
                                    "available_phys_ordered": [3, 4, 31],
                                    "blocked_candidates": [],
                                    "candidate_phys_ordered": [31],
                                    "chosen_source": "nonvolatile",
                                    "tie_rule": "fixture",
                                    "decision_rule": "retail",
                                    "confidence": "observed",
                                    "provenance": "retail-trace-fixture",
                                }
                            ],
                        }
                    ]
                },
            }
        ],
    }


def _write_backend_trace(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    path = tmp_path / "backend_trace.json"
    path.write_text(json.dumps(payload))
    return path


def _remove_backend_key(payload: dict, path: tuple[str | int, ...]) -> dict:
    out = copy.deepcopy(payload)
    current = out
    for key in path[:-1]:
        current = current[key]
    del current[path[-1]]
    return out


def test_backend_trace_rejects_object_shaped_functions(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_backend_trace

    payload = _minimal_backend_trace_payload()
    payload["functions"] = {
        "test_fn": {
            "name": "test_fn",
            "classes": payload["functions"][0]["regalloc"]["classes"],
        }
    }

    with pytest.raises(
        ValueError,
        match="backend trace missing required allocator facts: functions",
    ):
        facts_from_backend_trace(_write_backend_trace(tmp_path, payload), function="test_fn")


def test_backend_trace_rejects_function_missing_regalloc(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_backend_trace

    payload = _minimal_backend_trace_payload()
    function_payload = payload["functions"][0]
    function_payload["classes"] = function_payload["regalloc"]["classes"]
    del function_payload["regalloc"]

    with pytest.raises(
        ValueError,
        match="backend trace missing required allocator facts: regalloc",
    ):
        facts_from_backend_trace(_write_backend_trace(tmp_path, payload), function="test_fn")


@pytest.mark.parametrize(
    ("path", "field"),
    [
        (("functions", 0, "regalloc", "classes", 0, "edges"), "edges"),
        (
            (
                "functions",
                0,
                "regalloc",
                "classes",
                0,
                "registers",
                "allocatable",
            ),
            "allocatable",
        ),
        (
            (
                "functions",
                0,
                "regalloc",
                "classes",
                0,
                "nodes",
                0,
                "first_def",
            ),
            "first_def",
        ),
        (
            (
                "functions",
                0,
                "regalloc",
                "classes",
                0,
                "color_decisions",
                0,
                "available_phys_ordered",
            ),
            "available_phys_ordered",
        ),
    ],
)
def test_backend_trace_rejects_missing_required_allocator_fields(
    tmp_path: pathlib.Path,
    path: tuple[str | int, ...],
    field: str,
) -> None:
    from src.mwcc_debug.pressure_explorer.facts import facts_from_backend_trace

    payload = _remove_backend_key(_minimal_backend_trace_payload(), path)

    with pytest.raises(
        ValueError,
        match=rf"backend trace missing required allocator facts: .*{field}",
    ):
        facts_from_backend_trace(_write_backend_trace(tmp_path, payload), function="test_fn")


def test_source_attribution_status_uses_confidence_and_temp_kind() -> None:
    from src.mwcc_debug.pressure_explorer.facts import _source_attribution_fact

    def attribution(kind: str, confidence: str) -> SimpleNamespace:
        source = SimpleNamespace(
            name="temp",
            expression=None,
            kind=kind,
            source_file=None,
            source_line=None,
            source_col=None,
            confidence=confidence,
        )
        return SimpleNamespace(source=source)

    assert _source_attribution_fact(attribution("local", "low")).status == "ambiguous"
    assert (
        _source_attribution_fact(attribution("implicit-temp", "unknown")).status
        == "unattributed"
    )
    assert (
        _source_attribution_fact(
            attribution("copy/coalesce-product", "unknown")
        ).status
        == "unattributed"
    )
    assert _source_attribution_fact(attribution("local", "exact")).status == "attributed"


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
