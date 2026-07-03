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
    BlockedCandidate,
    Blocker,
    CoalesceFacts,
    ColorDecision,
    FirstDefSite,
    FunctionFacts,
    FunctionFreshness,
    InterferenceEdge,
    LifetimePressureReport,
    LiveFacts,
    RegisterFacts,
    SourceAttributionFact,
    SpillFacts,
    TargetAllocation,
    TargetPressureReport,
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
    assert comparison.target_results["0:40"]["satisfied"] is True
    assert comparison.target_results["0:37"]["regressed"] is True


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
    assert comparison.target_results["0:40"]["satisfied"] is True
    assert comparison.target_results["0:40"]["improved"] is True


def test_candidate_comparison_preserves_mixed_class_targets_with_same_ig(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.pressure_explorer import candidates as candidate_module
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps

    base_path = tmp_path / "base.pcdump.txt"
    cand_path = tmp_path / "candidate.pcdump.txt"
    base_path.write_text(PCDUMP)
    cand_path.write_text(CANDIDATE_PCDUMP)

    def two_class_facts(
        *,
        gpr_phys: int,
        fpr_phys: int,
    ) -> AllocatorFacts:
        return AllocatorFacts(
            schema_version="allocator-facts.v1",
            producer={"kind": "unit-test", "path": str(base_path)},
            function=FunctionFacts(
                name="fn_80000000",
                source_path=None,
                freshness=FunctionFreshness(status="fresh"),
            ),
            classes=(
                AllocatorClassFacts(
                    class_id=0,
                    class_name="gpr",
                    registers=RegisterFacts(physical_count=32, allocatable=(25, 26)),
                    nodes=(_manual_node(40, assigned_phys=gpr_phys),),
                    color_decisions=(_manual_decision(40, assigned_phys=gpr_phys),),
                ),
                AllocatorClassFacts(
                    class_id=1,
                    class_name="fpr",
                    registers=RegisterFacts(physical_count=32, allocatable=(14, 15)),
                    nodes=(_manual_node(40, assigned_phys=fpr_phys),),
                    color_decisions=(_manual_decision(40, assigned_phys=fpr_phys),),
                ),
            ),
        )

    baseline = two_class_facts(gpr_phys=26, fpr_phys=15)
    candidate = two_class_facts(gpr_phys=25, fpr_phys=14)
    monkeypatch.setattr(
        candidate_module,
        "facts_from_pcdump",
        lambda *args, **kwargs: candidate,
    )

    comparison = compare_candidate_pcdumps(
        baseline,
        TargetSet(
            targets=(
                TargetAllocation(class_id=0, ig_id=40, expected_phys=25),
                TargetAllocation(class_id=1, ig_id=40, expected_phys=14),
            )
        ),
        candidates=[("mixed", cand_path)],
    )[0]

    assert set(comparison.target_results) == {"0:40", "1:40"}
    assert comparison.target_results["0:40"]["class_id"] == 0
    assert comparison.target_results["0:40"]["candidate_phys"] == 25
    assert comparison.target_results["1:40"]["class_id"] == 1
    assert comparison.target_results["1:40"]["candidate_phys"] == 14
    assert comparison.pressure_delta["status"] == "unavailable"
    assert "mixed register classes" in comparison.pressure_delta["reason"]


def test_candidate_comparison_rejects_missing_baseline_target(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.candidates import compare_candidate_pcdumps
    from src.mwcc_debug.pressure_explorer.facts import facts_from_pcdump
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    base_text = (
        CANDIDATE_PCDUMP.replace("add r40", "add r42")
        .replace("1 40 1", "1 42 1")
        .replace("1 40 r25", "1 42 r25")
        .replace("40=r25", "42=r25")
    )
    base_path = tmp_path / "base.pcdump.txt"
    cand_path = tmp_path / "candidate.pcdump.txt"
    base_path.write_text(base_text)
    cand_path.write_text(CANDIDATE_PCDUMP)
    baseline = facts_from_pcdump(
        base_text,
        "fn_80000000",
        pcdump_path=base_path,
        source_text=SOURCE,
        class_filter=(0,),
    )
    target = parse_force_phys_spec("40:25", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("stale", cand_path)],
        source_text=SOURCE,
    )[0]

    assert comparison.status == "rejected"
    assert comparison.target_results["0:40"]["unsafe"] is True
    assert "baseline target not found" in comparison.target_results["0:40"]["warning"]


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
    assert comparison.target_results["0:40"]["satisfied"] is True
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
    assert comparison.target_results["0:40"]["improved"] is True
    assert comparison.target_results["0:37"]["satisfied"] is False
    assert comparison.target_results["0:37"]["regressed"] is False


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
        def from_text(cls, text: str, function: str, source: str) -> StubCompile:
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
    assert comparison.target_results["0:40"]["satisfied"] is True
    assert ("reanchor", 0) in calls


def test_candidate_comparison_suppresses_pressure_delta_for_reanchored_ids(
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
            force_phys={41: 27},
            diagnostics={},
            matched={41: 40},
        )

    monkeypatch.setattr(role_descriptor, "Compile", StubCompile)
    monkeypatch.setattr(role_descriptor, "build_target_spec", build_target_spec)
    monkeypatch.setattr(role_reanchor, "reanchor", reanchor)

    base_path = tmp_path / "base.pcdump.txt"
    cand_path = tmp_path / "candidate.pcdump.txt"
    base_path.write_text(PCDUMP)
    cand_path.write_text(PCDUMP)
    baseline = facts_from_pcdump(
        PCDUMP,
        "fn_80000000",
        pcdump_path=base_path,
        source_text=SOURCE,
        class_filter=(0,),
    )
    target = parse_force_phys_spec("40:27", default_class_id=0)

    comparison = compare_candidate_pcdumps(
        baseline,
        target,
        candidates=[("renumbered", cand_path)],
        source_text=SOURCE,
        require_reanchor=True,
    )[0]

    assert comparison.target_results["0:40"]["candidate_ig_id"] == 41
    assert comparison.pressure_delta["status"] == "unavailable"
    assert "reanchored candidate ids" in comparison.pressure_delta["reason"]


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
    assert comparison.target_results["0:40"]["unsafe"] is True
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
    assert comparison.target_results["0:40"]["unsafe"] is True


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


def test_render_text_and_json_include_fact_guess_split() -> None:
    from src.mwcc_debug.pressure_explorer import (
        render_json_report,
        render_text_report,
    )
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
    report = attach_hypotheses(
        analyze_lifetime_pressure(facts, parse_force_phys_spec("40:25")),
        pcdump_path="baseline.pcdump.txt",
        source_path="src/example.c",
        allow_stale_pcdump=False,
    )

    text = render_text_report(report)
    expected_sections = [
        "LIFETIME PRESSURE - FN_80000000",
        "INPUTS",
        "TARGET SUMMARY",
        "ALLOCATOR FACTS",
        "BLOCKERS",
        "SOURCE GUESSES",
        "HYPOTHESES",
        "VALIDATION COMMANDS",
        "CANDIDATE COMPARISONS",
        "WARNINGS",
    ]

    assert [text.index(section) for section in expected_sections] == sorted(
        text.index(section) for section in expected_sections
    )
    assert "expected_phys_holder" in text
    assert "debug mutate lifetime-layout" in text
    assert "schema_version" not in text
    json_report = render_json_report(report)
    assert json_report["schema_version"] == "lifetime-pressure-report.v1"
    assert json_report["targets"][0]["status"] == "blocked"
    assert json_report["source_attribution"]["status"] == "ranked"


def test_dot_and_blocker_table_outputs() -> None:
    from src.mwcc_debug.pressure_explorer import (
        render_blocker_table_csv,
        render_blocker_table_json,
        render_dot,
    )
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    report = analyze_lifetime_pressure(
        _parsed_pressure_facts(),
        parse_force_phys_spec("40:25", default_class_id=0),
    )

    dot = render_dot(report)
    csv_table = render_blocker_table_csv(report)
    json_table = render_blocker_table_json(report)

    assert "digraph lifetime_pressure" in dot
    assert "ig40" in dot
    assert "ig37" in dot
    assert "c0_ig37 -> c0_ig40" in dot
    assert "expected_phys_holder" in dot
    assert csv_table.startswith("target_ig,blocker_ig,target_class,blocker_class")
    assert "40,37,0,0,expected_phys_holder" in csv_table
    assert "expected phys r25" in csv_table
    assert json_table == [
        {
            "target_ig": 40,
            "blocker_ig": 37,
            "target_class": 0,
            "blocker_class": 0,
            "kind": "expected_phys_holder",
            "assigned_phys": 25,
            "impact": 100,
            "reason": "expected phys r25 is held by interfering IG 37",
            "source_summary": "obj->xC / field-load",
            "confidence": "observed",
        }
    ]


def test_render_class_aware_phys_labels_and_dot_ids_do_not_collide() -> None:
    from src.mwcc_debug.pressure_explorer import render_dot, render_text_report

    gpr_blocker = Blocker(
        target_ig_id=40,
        ig_id=41,
        kind="expected_phys_holder",
        assigned_phys=25,
        impact=100,
        reason="expected phys r25 is held by interfering IG 41",
    )
    fpr_blocker = Blocker(
        target_ig_id=40,
        ig_id=41,
        kind="expected_phys_holder",
        assigned_phys=25,
        impact=100,
        reason="expected phys f25 is held by interfering IG 41",
    )
    gpr_target = TargetPressureReport(
        class_id=0,
        ig_id=40,
        virtual={"kind": "gpr", "number": 40},
        current_phys=24,
        expected_phys=25,
        status="blocked",
        first_def=None,
        source_attribution=SourceAttributionFact(status="attributed", symbol="gpr"),
        live=LiveFacts(),
        simplify_order=1,
        select_order=1,
        coalesce=CoalesceFacts(root_ig_id=40),
        spill=SpillFacts(spilled=False),
        blockers=(gpr_blocker,),
        why_current_color="mwcc-colorgraph selected r24",
        must_change=("remove gpr interference",),
        confidence="observed",
    )
    fpr_target = TargetPressureReport(
        class_id=1,
        ig_id=40,
        virtual={"kind": "fpr", "number": 40},
        current_phys=24,
        expected_phys=25,
        status="blocked",
        first_def=None,
        source_attribution=SourceAttributionFact(status="attributed", symbol="fpr"),
        live=LiveFacts(),
        simplify_order=1,
        select_order=1,
        coalesce=CoalesceFacts(root_ig_id=40),
        spill=SpillFacts(spilled=False),
        blockers=(fpr_blocker,),
        why_current_color="mwcc-colorgraph selected f24",
        must_change=("remove fpr interference",),
        confidence="observed",
    )
    report = LifetimePressureReport(
        schema_version="lifetime-pressure-report.v1",
        function="fn_80000000",
        inventory_only=False,
        inputs={},
        targets=(gpr_target, fpr_target),
        allocator_facts=AllocatorFacts(
            schema_version="allocator-facts.v1",
            producer={"kind": "unit-test"},
            function=FunctionFacts(
                name="fn_80000000",
                source_path=None,
                freshness=FunctionFreshness(status="fresh"),
            ),
            classes=(),
        ),
        blockers=(gpr_blocker, fpr_blocker),
        source_attribution={"status": "not_ranked"},
        hypotheses=(),
        validation_commands=(),
    )

    text = render_text_report(report)
    dot = render_dot(report)

    assert "class=1 status=blocked current=f24 expected=f25" in text
    assert "class=1 status=blocked current=r24 expected=r25" not in text
    assert "c0_ig40" in dot
    assert "c1_ig40" in dot
    assert "c0_ig41 -> c0_ig40" in dot
    assert "c1_ig41 -> c1_ig40" in dot
    assert "expected f25" in dot
    assert "expected r25" in dot


def test_blocker_tables_include_class_context_for_duplicate_igs() -> None:
    from src.mwcc_debug.pressure_explorer import (
        render_blocker_table_csv,
        render_blocker_table_json,
    )

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
        source_attribution=SourceAttributionFact(status="attributed", symbol="fpr"),
        live=LiveFacts(),
        simplify_order=1,
        select_order=1,
        coalesce=CoalesceFacts(root_ig_id=40),
        spill=SpillFacts(spilled=False),
        blockers=(blocker,),
        why_current_color="mwcc-colorgraph selected f24",
        must_change=("remove fpr interference",),
        confidence="observed",
    )
    report = LifetimePressureReport(
        schema_version="lifetime-pressure-report.v1",
        function="fn_80000000",
        inventory_only=False,
        inputs={},
        targets=(target,),
        allocator_facts=AllocatorFacts(
            schema_version="allocator-facts.v1",
            producer={"kind": "unit-test"},
            function=FunctionFacts(
                name="fn_80000000",
                source_path=None,
                freshness=FunctionFreshness(status="fresh"),
            ),
            classes=(),
        ),
        blockers=(blocker,),
        source_attribution={"status": "not_ranked"},
        hypotheses=(),
        validation_commands=(),
    )

    csv_table = render_blocker_table_csv(report)
    json_table = render_blocker_table_json(report)

    assert csv_table.startswith("target_ig,blocker_ig,target_class,blocker_class")
    assert "40,41,1,1,expected_phys_holder" in csv_table
    assert json_table == [
        {
            "target_ig": 40,
            "blocker_ig": 41,
            "target_class": 1,
            "blocker_class": 1,
            "kind": "expected_phys_holder",
            "assigned_phys": 25,
            "impact": 100,
            "reason": "expected phys f25 is held by interfering IG 41",
            "source_summary": None,
            "confidence": "observed",
        }
    ]


def test_renderer_outputs_class_aware_analyzer_fpr_blocker_reasons() -> None:
    from src.mwcc_debug.pressure_explorer import (
        render_blocker_table_csv,
        render_blocker_table_json,
        render_dot,
        render_text_report,
    )
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure
    from src.mwcc_debug.pressure_explorer.targets import parse_force_phys_spec

    facts = AllocatorFacts(
        schema_version="allocator-facts.v1",
        producer={"kind": "unit-test"},
        function=FunctionFacts(
            name="fn_80000000",
            source_path=None,
            freshness=FunctionFreshness(status="fresh"),
        ),
        classes=(
            AllocatorClassFacts(
                class_id=1,
                class_name="fpr",
                registers=RegisterFacts(physical_count=32, allocatable=(24, 25)),
                nodes=(
                    AllocatorNode(
                        ig_id=40,
                        virtual_kind="fpr",
                        virtual_number=40,
                        color_status="colored",
                        coalesced_into=None,
                        color_decision_ref="fpr-c40",
                        first_def=FirstDefSite(opcode="fadds", operands="f40, f1, f2"),
                        source_attribution=SourceAttributionFact(
                            status="attributed",
                            symbol="target",
                        ),
                        live=LiveFacts(blocks=("B0",), intervals=((0, 2),)),
                        degree=1,
                        flags=(),
                        coalesce=CoalesceFacts(root_ig_id=40),
                        simplify_order=0,
                        select_order=0,
                        assigned_phys=24,
                        spill=SpillFacts(spilled=False),
                    ),
                    AllocatorNode(
                        ig_id=41,
                        virtual_kind="fpr",
                        virtual_number=41,
                        color_status="colored",
                        coalesced_into=None,
                        color_decision_ref="fpr-c41",
                        first_def=FirstDefSite(opcode="fmr", operands="f41, f3"),
                        source_attribution=SourceAttributionFact(
                            status="attributed",
                            symbol="holder",
                        ),
                        live=LiveFacts(blocks=("B0",), intervals=((0, 2),)),
                        degree=1,
                        flags=(),
                        coalesce=CoalesceFacts(root_ig_id=41),
                        simplify_order=1,
                        select_order=1,
                        assigned_phys=25,
                        spill=SpillFacts(spilled=False),
                    ),
                ),
                edges=(InterferenceEdge(40, 41),),
                color_decisions=(
                    ColorDecision(
                        id="fpr-c40",
                        ig_id=40,
                        iter=0,
                        assigned_phys=24,
                        available_phys_ordered=(24, 25),
                        blocked_candidates=(
                            BlockedCandidate(
                                phys=25,
                                holder_ig_id=41,
                                holder_assigned_phys=25,
                                reason="interferes",
                            ),
                        ),
                        candidate_phys_ordered=(24, 25),
                        chosen_source="observed",
                        decision_rule="unit-test",
                        tie_rule="unit-test",
                        confidence="observed",
                    ),
                    ColorDecision(
                        id="fpr-c41",
                        ig_id=41,
                        iter=1,
                        assigned_phys=25,
                        available_phys_ordered=(24, 25),
                        blocked_candidates=(),
                        candidate_phys_ordered=(24, 25),
                        chosen_source="observed",
                        decision_rule="unit-test",
                        tie_rule="unit-test",
                        confidence="observed",
                    ),
                ),
            ),
        ),
    )
    report = analyze_lifetime_pressure(
        facts,
        parse_force_phys_spec("40:25", default_class_id=1),
    )

    text = render_text_report(report)
    dot = render_dot(report)
    csv_table = render_blocker_table_csv(report)
    json_table = render_blocker_table_json(report)

    assert "current=f24 expected=f25" in text
    assert "expected phys f25 is held by interfering IG 41" in text
    assert "unit-test selected f24 from observed" in text
    assert "expected phys r25" not in text
    assert "selected r24" not in text
    assert "expected f25" in dot
    assert "expected r25" not in dot
    assert "expected phys f25 is held by interfering IG 41" in csv_table
    assert "expected phys r25" not in csv_table
    assert json_table[0]["reason"] == "expected phys f25 is held by interfering IG 41"


def test_render_text_no_target_mode_is_inventory_only_without_blocker_claims() -> None:
    from src.mwcc_debug.pressure_explorer import render_text_report
    from src.mwcc_debug.pressure_explorer.analyzer import analyze_lifetime_pressure

    report = analyze_lifetime_pressure(_parsed_pressure_facts(), target_set=None)

    text = render_text_report(report)

    assert "inventory-only: no target allocation supplied" in text
    assert "expected_phys_holder" not in text
    assert "blocked by" not in text.lower()


def _score_source_payload(
    *,
    matched: int,
    targeted: int = 2,
    structural_rejection: bool = False,
    checkdiff_accepted: bool = True,
    structural_accepted: bool = True,
) -> dict[str, object]:
    return {
        "target_score": {
            "matched": matched,
            "targeted": targeted,
            "virtuals": {
                "37": {
                    "matched": matched >= 1,
                    "baseline_matched": False,
                },
                "40": {
                    "matched": matched >= 2,
                    "baseline_matched": False,
                },
            },
        },
        "force_phys_score": {
            "force_phys_hits": matched,
            "structural_rejection": structural_rejection,
        },
        "checkdiff_guard": {"accepted": checkdiff_accepted},
        "structural_guard": {"accepted": structural_accepted},
    }


def test_remote_validation_is_emit_only(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.validation import (
        build_remote_validation_plan,
    )

    candidates = [tmp_path / "candidate_a.c", tmp_path / "candidate_b.c"]

    commands = build_remote_validation_plan(
        function="fn_80000000",
        force_phys="37:25,40:26",
        timeout=45,
        campaign_dir=tmp_path / "campaign",
        source_candidates=candidates,
    )

    assert commands
    assert {command.mode for command in commands} == {"emit"}
    assert all("--remote-fallback" in command.command for command in commands)
    assert all("--timeout 45" in command.command for command in commands)
    assert str(tmp_path / "campaign") in commands[0].command
    assert "fn_80000000.force-phys.target.yaml" in commands[0].command
    assert "force_phys_target.yaml" not in commands[0].command
    assert str(candidates[0]) in commands[0].command
    assert str(candidates[1]) in commands[1].command


def test_validation_api_reexports_from_pressure_explorer_package() -> None:
    from src.mwcc_debug.pressure_explorer import (
        build_remote_validation_plan,
        materialize_force_phys_target_spec,
        run_bounded_validation,
        run_quick_validation,
    )

    assert callable(build_remote_validation_plan)
    assert callable(materialize_force_phys_target_spec)
    assert callable(run_bounded_validation)
    assert callable(run_quick_validation)


def test_materialize_force_phys_target_spec_writes_score_source_contract(
    tmp_path: pathlib.Path,
) -> None:
    import yaml

    from src.mwcc_debug.pressure_explorer.validation import (
        materialize_force_phys_target_spec,
    )

    baseline = tmp_path / "baseline.pcdump.txt"

    target = materialize_force_phys_target_spec(
        function="fn_80000000",
        class_id=0,
        force_phys="37:25,40:26",
        baseline_dump=baseline,
        output_dir=tmp_path / "out",
    )

    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data == {
        "function": "fn_80000000",
        "class_id": 0,
        "baseline_dump": str(baseline),
        "force_phys": {37: 25, 40: 26},
        "coalesce_preservation": True,
    }
    assert all(isinstance(key, int) for key in data["force_phys"])


def test_remote_validation_uses_materialized_target_file(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.validation import (
        build_remote_validation_plan,
        materialize_force_phys_target_spec,
    )

    target_file = materialize_force_phys_target_spec(
        function="fn_80000000",
        class_id=0,
        force_phys="37:25",
        baseline_dump=tmp_path / "baseline.pcdump.txt",
        output_dir=tmp_path / "campaign",
    )

    commands = build_remote_validation_plan(
        function="fn_80000000",
        force_phys="37:25",
        timeout=45,
        campaign_dir=tmp_path / "campaign",
        source_candidates=[tmp_path / "candidate.c"],
        target_file=target_file,
    )

    assert f"--target {target_file}" in commands[0].command


def test_validation_public_functions_are_keyword_only(tmp_path: pathlib.Path) -> None:
    from src.mwcc_debug.pressure_explorer.validation import (
        build_remote_validation_plan,
        run_quick_validation,
    )

    with pytest.raises(TypeError):
        build_remote_validation_plan(
            "fn_80000000",
            "37:25",
            45,
            tmp_path / "campaign",
            [tmp_path / "candidate.c"],
        )
    with pytest.raises(TypeError):
        run_quick_validation(
            "fn_80000000",
            tmp_path / "target.yaml",
            [tmp_path / "candidate.c"],
            30,
        )


def test_zero_validation_timeout_disables_subprocess_timeout_but_keeps_cli_arg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer import validation

    subprocess_timeouts: list[float | None] = []

    def fake_run(
        argv: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float | None,
        check: bool,
    ) -> SimpleNamespace:
        subprocess_timeouts.append(timeout)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(validation.subprocess, "run", fake_run)

    validation._subprocess_runner(["melee-agent"], timeout=0)

    quick_calls: list[tuple[list[str], int]] = []

    def runner(argv: list[str], timeout: int) -> dict[str, object]:
        quick_calls.append((argv, timeout))
        return {"returncode": 0, "stdout": "{}", "stderr": ""}

    validation.run_quick_validation(
        function="fn_80000000",
        target_file=tmp_path / "target.yaml",
        source_candidates=[tmp_path / "candidate.c"],
        timeout=0,
        runner=runner,
    )

    assert subprocess_timeouts == [None]
    argv, runner_timeout = quick_calls[0]
    assert argv[argv.index("--timeout") + 1] == "0"
    assert runner_timeout == 0


def test_quick_validation_runs_supplied_source_candidates_with_runner(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.validation import run_quick_validation

    target = tmp_path / "target.yaml"
    candidates = [tmp_path / "candidate.c"]
    calls: list[tuple[list[str], int]] = []

    def runner(argv: list[str], timeout: int) -> dict[str, object]:
        calls.append((argv, timeout))
        return {
            "returncode": 0,
            "stdout": json.dumps(_score_source_payload(matched=2)),
            "stderr": "",
        }

    results = run_quick_validation(
        function="fn_80000000",
        target_file=target,
        source_candidates=candidates,
        timeout=30,
        runner=runner,
    )

    assert results[0]["status"] == "full_target_match"
    assert results[0]["target_score"]["matched"] == 2
    assert calls == [
        (
            [
                "melee-agent",
                "debug",
                "target",
                "score-source",
                str(candidates[0]),
                "-f",
                "fn_80000000",
                "--target",
                str(target),
                "--json",
                "--retain-pcdump",
                "--checkdiff-guard",
                "--timeout",
                "30",
            ],
            30,
        )
    ]


def test_quick_validation_classifies_partial_progress_and_rejections(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.validation import run_quick_validation

    payloads = [
        _score_source_payload(matched=1),
        _score_source_payload(matched=2, structural_rejection=True),
        _score_source_payload(matched=2, checkdiff_accepted=False),
        _score_source_payload(matched=0),
    ]

    def runner(_argv: list[str], _timeout: int) -> dict[str, object]:
        return {
            "returncode": 0,
            "stdout": json.dumps(payloads.pop(0)),
            "stderr": "",
        }

    results = run_quick_validation(
        function="fn_80000000",
        target_file=tmp_path / "target.yaml",
        source_candidates=[
            tmp_path / "partial.c",
            tmp_path / "structural_reject.c",
            tmp_path / "guard_reject.c",
            tmp_path / "miss.c",
        ],
        timeout=30,
        runner=runner,
    )

    assert [result["status"] for result in results] == [
        "partial_progress",
        "rejected",
        "rejected",
        "rejected",
    ]


def test_bounded_validation_runs_existing_mutation_workflows(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.validation import run_bounded_validation

    calls: list[list[str]] = []

    def runner(argv: list[str], _timeout: int) -> dict[str, object]:
        calls.append(argv)
        return {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""}

    results = run_bounded_validation(
        function="fn_80000000",
        force_phys="37:25",
        pcdump_path=tmp_path / "base.pcdump.txt",
        source_path=tmp_path / "source.c",
        timeout=60,
        max_candidates=7,
        runner=runner,
    )

    assert [result["status"] for result in results] == [
        "partial_progress",
        "partial_progress",
    ]
    assert calls == [
        [
            "melee-agent",
            "debug",
            "mutate",
            "lifetime-layout",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(tmp_path / "base.pcdump.txt"),
            "--source-file",
            str(tmp_path / "source.c"),
            "--compile-probes",
            "--max-probes",
            "7",
            "--timeout",
            "60",
            "--json",
        ],
        [
            "melee-agent",
            "debug",
            "mutate",
            "simplify-order",
            "-f",
            "fn_80000000",
            "--force-phys",
            "37:25",
            "--source-file",
            str(tmp_path / "source.c"),
            "--pcdump",
            str(tmp_path / "base.pcdump.txt"),
            "--max-candidates",
            "7",
            "--timeout",
            "60",
            "--json",
        ],
    ]


def test_bounded_validation_runs_select_order_for_direct_blockers(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.validation import run_bounded_validation

    calls: list[list[str]] = []

    def runner(argv: list[str], _timeout: int) -> dict[str, object]:
        calls.append(argv)
        return {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""}

    results = run_bounded_validation(
        function="fn_80000000",
        force_phys="40:25",
        pcdump_path=tmp_path / "base.pcdump.txt",
        source_path=tmp_path / "source.c",
        timeout=60,
        max_candidates=7,
        direct_blockers=[(0, 40, 37)],
        runner=runner,
    )

    assert len(results) == 3
    select_order = calls[2]
    assert select_order[:4] == [
        "melee-agent",
        "debug",
        "select-order-search",
        "-f",
    ]
    assert "debug" in select_order
    assert "select-order-search" in select_order
    assert select_order[select_order.index("--target") + 1] == "r40<r37"
    assert select_order[select_order.index("--force-phys") + 1] == "40:25"
    assert select_order[select_order.index("--pcdump") + 1] == str(
        tmp_path / "base.pcdump.txt"
    )
    assert select_order[select_order.index("--source-file") + 1] == str(
        tmp_path / "source.c"
    )
    assert select_order[select_order.index("--max-probes") + 1] == "7"
    assert select_order[select_order.index("--timeout") + 1] == "60"
    assert "--json" in select_order


def test_bounded_validation_uses_fpr_direct_blocker_target(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.validation import run_bounded_validation

    calls: list[list[str]] = []

    def runner(argv: list[str], _timeout: int) -> dict[str, object]:
        calls.append(argv)
        return {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""}

    run_bounded_validation(
        function="fn_80000000",
        force_phys="1:40:25",
        pcdump_path=tmp_path / "base.pcdump.txt",
        source_path=tmp_path / "source.c",
        timeout=60,
        max_candidates=7,
        direct_blockers=[(1, 40, 37)],
        runner=runner,
    )

    select_order = calls[2]
    assert select_order[select_order.index("--target") + 1] == "f40<f37"
    assert "r40<r37" not in select_order
    assert "--class" in select_order
    assert select_order[select_order.index("--class") + 1] == "1"


def test_build_lifetime_pressure_report_combines_analysis_and_hypotheses(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.lifetime_pressure import (
        build_lifetime_pressure_report,
    )

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "source.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)
    pcdump.touch()

    report = build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=PCDUMP,
        pcdump_path=pcdump,
        source_text=SOURCE,
        source_path=source,
        force_phys="40:25",
        target_path=None,
        candidates=[],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="none",
        timeout=120,
        max_candidates=100,
    )

    assert report.function == "fn_80000000"
    assert report.targets[0].status == "blocked"
    assert report.hypotheses
    assert report.validation_commands


def test_build_lifetime_pressure_report_inventory_only_has_derive_command(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.lifetime_pressure import (
        build_lifetime_pressure_report,
    )

    pcdump = tmp_path / "base.pcdump.txt"
    pcdump.write_text(PCDUMP)

    report = build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=None,
        pcdump_path=pcdump,
        source_text=None,
        source_path=None,
        force_phys=None,
        target_path=None,
        candidates=[],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="none",
        timeout=120,
        max_candidates=100,
    )

    assert report.inventory_only is True
    assert report.hypotheses == ()
    assert any("derive a target" in cmd.command for cmd in report.validation_commands)


def test_build_lifetime_pressure_report_attaches_pcdump_candidate_comparisons(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.lifetime_pressure import (
        build_lifetime_pressure_report,
    )

    pcdump = tmp_path / "base.pcdump.txt"
    candidate = tmp_path / "candidate.pcdump.txt"
    pcdump.write_text(PCDUMP)
    candidate.write_text(CANDIDATE_PCDUMP)

    report = build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=PCDUMP,
        pcdump_path=pcdump,
        source_text=SOURCE,
        source_path=None,
        force_phys="40:25",
        target_path=None,
        candidates=[f"try1={candidate}"],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="none",
        timeout=120,
        max_candidates=100,
    )

    assert [comparison.label for comparison in report.candidate_comparisons] == ["try1"]
    assert report.candidate_comparisons[0].path == str(candidate)


def test_build_lifetime_pressure_report_remote_source_candidate_is_dry_run_only(
    tmp_path: pathlib.Path,
) -> None:
    from src.mwcc_debug.pressure_explorer.lifetime_pressure import (
        build_lifetime_pressure_report,
    )

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "candidate.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    report = build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=PCDUMP,
        pcdump_path=pcdump,
        source_text=SOURCE,
        source_path=source,
        force_phys="40:25",
        target_path=None,
        candidates=[f"source_try={source}"],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="remote",
        timeout=45,
        max_candidates=100,
    )

    assert report.candidate_comparisons == ()
    assert any(
        command.id.startswith("remote-score-source")
        and str(source) in command.command
        and "--remote-fallback" in command.command
        for command in report.validation_commands
    )


def test_build_lifetime_pressure_report_quick_materializes_force_phys_target(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.pressure_explorer import lifetime_pressure

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "candidate.c"
    target_file = tmp_path / "materialized.target.yaml"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)
    calls: dict[str, object] = {}

    def fake_materialize_force_phys_target_spec(**kwargs: object) -> pathlib.Path:
        calls["materialize"] = kwargs
        target_file.write_text("target: true\n")
        return target_file

    def fake_run_quick_validation(**kwargs: object) -> list[dict[str, object]]:
        calls["quick"] = kwargs
        return [{"candidate": str(source), "status": "partial_progress"}]

    monkeypatch.setattr(
        lifetime_pressure,
        "materialize_force_phys_target_spec",
        fake_materialize_force_phys_target_spec,
    )
    monkeypatch.setattr(
        lifetime_pressure,
        "run_quick_validation",
        fake_run_quick_validation,
    )

    report = lifetime_pressure.build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=PCDUMP,
        pcdump_path=pcdump,
        source_text=SOURCE,
        source_path=source,
        force_phys="40:25",
        target_path=None,
        candidates=[f"source_try={source}"],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="quick",
        timeout=30,
        max_candidates=100,
    )

    assert calls["materialize"]["baseline_dump"] == pcdump
    assert calls["materialize"]["output_dir"] == tmp_path
    assert calls["quick"]["target_file"] == target_file
    assert calls["quick"]["source_candidates"] == [source]
    assert report.outputs["quick_validation"][0]["status"] == "partial_progress"


def test_build_lifetime_pressure_report_bounded_passes_direct_blockers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.pressure_explorer import lifetime_pressure

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "source.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)
    calls: dict[str, object] = {}

    def fake_run_bounded_validation(**kwargs: object) -> list[dict[str, object]]:
        calls["bounded"] = kwargs
        return [{"candidate": "select-order-0-40-37", "status": "partial_progress"}]

    monkeypatch.setattr(
        lifetime_pressure,
        "run_bounded_validation",
        fake_run_bounded_validation,
    )

    report = lifetime_pressure.build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=PCDUMP,
        pcdump_path=pcdump,
        source_text=SOURCE,
        source_path=source,
        force_phys="40:25",
        target_path=None,
        candidates=[],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="bounded",
        timeout=30,
        max_candidates=8,
    )

    assert calls["bounded"]["direct_blockers"] == [(0, 40, 37)]
    assert calls["bounded"]["force_phys"] == "40:25"
    assert report.outputs["bounded_validation"][0]["candidate"] == "select-order-0-40-37"


def test_build_lifetime_pressure_report_bounded_validates_source_candidates(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.mwcc_debug.pressure_explorer import lifetime_pressure

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "source.c"
    candidate = tmp_path / "candidate.c"
    target_file = tmp_path / "materialized.target.yaml"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)
    candidate.write_text(SOURCE)
    calls: dict[str, object] = {}

    def fake_materialize_force_phys_target_spec(**kwargs: object) -> pathlib.Path:
        calls["materialize"] = kwargs
        target_file.write_text("target: true\n")
        return target_file

    def fake_run_quick_validation(**kwargs: object) -> list[dict[str, object]]:
        calls["quick"] = kwargs
        return [{"candidate": str(candidate), "status": "full_target_match"}]

    def fake_run_bounded_validation(**kwargs: object) -> list[dict[str, object]]:
        calls["bounded"] = kwargs
        return [{"candidate": "lifetime-layout", "status": "partial_progress"}]

    monkeypatch.setattr(
        lifetime_pressure,
        "materialize_force_phys_target_spec",
        fake_materialize_force_phys_target_spec,
    )
    monkeypatch.setattr(
        lifetime_pressure,
        "run_quick_validation",
        fake_run_quick_validation,
    )
    monkeypatch.setattr(
        lifetime_pressure,
        "run_bounded_validation",
        fake_run_bounded_validation,
    )

    report = lifetime_pressure.build_lifetime_pressure_report(
        function="fn_80000000",
        pcdump_text=PCDUMP,
        pcdump_path=pcdump,
        source_text=SOURCE,
        source_path=source,
        force_phys="40:25",
        target_path=None,
        candidates=[f"candidate={candidate}"],
        backend_trace_path=None,
        class_id=0,
        allow_stale_pcdump=False,
        validate_mode="bounded",
        timeout=30,
        max_candidates=8,
    )

    assert calls["materialize"]["baseline_dump"] == pcdump
    assert calls["quick"]["target_file"] == target_file
    assert calls["quick"]["source_candidates"] == [candidate]
    assert calls["bounded"]["source_path"] == source
    assert report.outputs["bounded_source_validation"][0]["status"] == "full_target_match"
    assert report.outputs["bounded_validation"][0]["candidate"] == "lifetime-layout"


def test_lifetime_pressure_cli_json_smoke(tmp_path: pathlib.Path) -> None:
    from typer.testing import CliRunner

    from src.cli.debug import debug_app

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "source.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    result = CliRunner().invoke(
        debug_app,
        [
            "inspect",
            "lifetime-pressure",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--force-phys",
            "40:25",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "lifetime-pressure-report.v1"
    assert payload["function"] == "fn_80000000"
    assert payload["targets"][0]["status"] == "blocked"


def test_lifetime_pressure_cli_rejects_source_candidate_read_only(
    tmp_path: pathlib.Path,
) -> None:
    from typer.testing import CliRunner

    from src.cli.debug import debug_app

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "source.c"
    candidate = tmp_path / "candidate.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)
    candidate.write_text(SOURCE)

    result = CliRunner().invoke(
        debug_app,
        [
            "inspect",
            "lifetime-pressure",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--force-phys",
            "40:25",
            "--candidate",
            f"candidate={candidate}",
            "--validate",
            "none",
        ],
    )

    assert result.exit_code != 0
    assert "source candidate requires compile-capable validation mode" in result.output


def test_lifetime_pressure_cli_writes_dot_and_blocker_table(
    tmp_path: pathlib.Path,
) -> None:
    from typer.testing import CliRunner

    from src.cli.debug import debug_app

    pcdump = tmp_path / "base.pcdump.txt"
    source = tmp_path / "source.c"
    dot = tmp_path / "pressure.dot"
    table = tmp_path / "blockers.csv"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    result = CliRunner().invoke(
        debug_app,
        [
            "inspect",
            "lifetime-pressure",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--force-phys",
            "40:25",
            "--dot",
            str(dot),
            "--blocker-table",
            str(table),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "LIFETIME PRESSURE - FN_80000000" in result.output
    assert "digraph lifetime_pressure" in dot.read_text()
    assert "40,37,0,0,expected_phys_holder" in table.read_text()
