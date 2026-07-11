from __future__ import annotations

import hashlib
from types import MappingProxyType, SimpleNamespace

import pytest

from src.mwcc_debug import role_descriptor
from src.mwcc_debug.causal_diff.alignment import align_anchor, build_role_comparisons
from src.mwcc_debug.causal_diff.asm_adapter import (
    CheckdiffEvidence,
    CheckdiffInstruction,
    CheckdiffRow,
)
from src.mwcc_debug.causal_diff.backend_adapter import BackendEvidence
from src.mwcc_debug.causal_diff.differ import diff_frontiers
from src.mwcc_debug.causal_diff.effects import derive_effects
from src.mwcc_debug.causal_diff.frame_adapter import FrameEvidence
from src.mwcc_debug.causal_diff.graph import FrontierGraph
from src.mwcc_debug.causal_diff.models import (
    AdapterResult,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.source_adapter import SourceEvidence
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore


def _provenance(*input_record_ids: str) -> Provenance:
    return Provenance(
        artifact_sha256="a" * 64,
        parser="causal-alignment-test.v1",
        raw_start=None,
        raw_end=None,
        derivation_rule="unit-test-evidence",
        input_record_ids=tuple(input_record_ids),
    )


def _node(
    compile_id: str,
    kind: str,
    key: object,
    attributes: dict[str, object],
    *,
    role_key: str | None = None,
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=compile_id,
        function="fn_test",
        kind=kind,
        local_key=key,
        role_key=role_key,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_provenance(),
        attributes=attributes,
    )


def _edge(
    compile_id: str,
    kind: str,
    source: EvidenceNode,
    target: EvidenceNode,
    *,
    attributes: dict[str, object] | None = None,
) -> EvidenceEdge:
    return EvidenceEdge.create(
        compile_id=compile_id,
        function="fn_test",
        kind=kind,
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.DERIVED_UNIQUE,
        provenance=_provenance(source.record_id, target.record_id),
        input_confidences=(source.confidence, target.confidence),
        attributes={} if attributes is None else attributes,
    )


def _descriptor(ig: int, signature: str, uses: tuple[tuple[str, int], ...]) -> role_descriptor.RoleDescriptor:
    return role_descriptor.RoleDescriptor(
        ig_idx=ig,
        first_def_sig=signature,
        use_site_multiset=uses,
        is_param=False,
        var_name=None,
        var_confidence=None,
        assigned_reg=None,
        live_range=(0, 1),
        use_count=sum(count for _opcode, count in uses),
        spilled=False,
    )


@pytest.fixture(autouse=True)
def _descriptor_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.mwcc_debug.causal_diff.alignment.role_descriptor.build_descriptors",
        lambda compile_, class_id: compile_[class_id],
    )


def _graph(label: str, *, missing_use: bool = False, reused_register: bool = False) -> FrontierGraph:
    compile_id = hashlib.sha256(label.encode()).hexdigest()
    def_ig, use_ig = ((40, 41) if label == "direct" else (66, 67))
    current_regs = (("r", 22), ("r", 21)) if label == "direct" else (("r", 20), ("r", 19))
    expected = CheckdiffInstruction(
        offset=0x234,
        opcode="addi",
        operands="r22,r21,0",
        regs=(("r", 22), ("r", 21)),
        raw="+234: addi r22,r21,0",
    )
    current = CheckdiffInstruction(
        offset=0x234,
        opcode="addi",
        operands=f"r{current_regs[0][1]},r{current_regs[1][1]},0",
        regs=current_regs,
        raw=f"+234: addi r{current_regs[0][1]},r{current_regs[1][1]},0",
    )
    row = CheckdiffRow(offset=0x234, expected=expected, current=current)

    retail = _node(
        compile_id,
        "retail-instruction",
        "retail",
        {
            "offset": 0x234,
            "opcode": "addi",
            "operands": expected.operands,
            "regs": expected.regs,
            "neighborhood_signature": ("addi r#,r#,0",),
        },
        role_key="retail-offset:234",
    )
    candidate = _node(
        compile_id,
        "candidate-instruction",
        "candidate",
        {
            "offset": 0x234,
            "aligned_retail_offset": 0x234,
            "opcode": "addi",
            "operands": current.operands,
            "regs": current.regs,
            "retail_neighborhood_signature": ("addi r#,r#,0",),
        },
        role_key="retail-offset:234",
    )
    occurrence = _node(
        compile_id,
        "pcode-occurrence",
        "anchor-pcode",
        {
            "pass": "BEFORE REGISTER COLORING",
            "pass_index": 0,
            "block": 0,
            "instruction_index": 7,
            "opcode": "addi",
            "operands": f"r{def_ig},r{use_ig},0",
            "regs": (("r", def_ig), ("r", use_ig)),
            "operand_roles": (("def",), ("use",)),
        },
    )
    virtual_def = _node(compile_id, "virtual-register", f"v{def_ig}", {"class": "r", "virtual": def_ig})
    virtual_use = _node(compile_id, "virtual-register", f"v{use_ig}", {"class": "r", "virtual": use_ig})
    allocator_def = _node(
        compile_id,
        "allocator-node",
        f"ig{def_ig}",
        {
            "class_id": 0,
            "ig_id": def_ig,
            "assigned_reg": current_regs[0][1],
            "first_def_signature": "addi r#,r#,0",
            "select_order": 2 if label == "direct" else 3,
        },
    )
    allocator_use = _node(
        compile_id,
        "allocator-node",
        f"ig{use_ig}",
        {
            "class_id": 0,
            "ig_id": use_ig,
            "assigned_reg": current_regs[1][1],
            "first_def_signature": "lwz r#,0(r#)",
        },
    )

    # The lexicographically first frontier intentionally has the stack mismatch;
    # the second has the allocator mismatch. This creates one eligible effect pair.
    stack_start = 36 if label == "direct" else 32
    stack = _node(
        compile_id,
        "stack-object",
        "row-stack",
        {
            "side": "current",
            "start": stack_start,
            "end": stack_start + 4,
            "size": 4,
            "layout_order": 0,
            "access_interval": (7, 11),
        },
        role_key="row",
    )
    nodes = [retail, candidate, occurrence, virtual_def, virtual_use, allocator_def, allocator_use, stack]
    edges = [
        _edge(compile_id, "aligns-to-retail", candidate, retail, attributes={"retail_offset": 0x234}),
        _edge(compile_id, "defines-virtual", occurrence, virtual_def, attributes={"operand_position": 0}),
        _edge(compile_id, "maps-to-allocator-node", virtual_def, allocator_def),
        _edge(compile_id, "maps-to-allocator-node", virtual_use, allocator_use),
        _edge(compile_id, "materializes-as-stack-object", allocator_def, stack),
    ]
    if not missing_use:
        edges.append(_edge(compile_id, "uses-virtual", occurrence, virtual_use, attributes={"operand_position": 1}))

    descriptors = {
        def_ig: _descriptor(def_ig, "addi r#,r#,0", (("stw", 1),)),
        use_ig: _descriptor(use_ig, "lwz r#,0(r#)", (("addi", 1),)),
    }
    nodes_by_class_ig = {(0, def_ig): allocator_def.record_id, (0, use_ig): allocator_use.record_id}
    if reused_register and label == "paired":
        reused = _node(
            compile_id,
            "allocator-node",
            "ig58",
            {
                "class_id": 0,
                "ig_id": 58,
                "assigned_reg": 22,
                "first_def_signature": "addi r#,r#,4",
            },
        )
        nodes.append(reused)
        descriptors[58] = _descriptor(58, "addi r#,r#,4", (("cmpi", 1),))
        nodes_by_class_ig[(0, 58)] = reused.record_id

    store = InMemoryEvidenceStore()
    store.add_nodes(nodes)
    store.add_edges(edges)
    checkdiff = CheckdiffEvidence(
        result=AdapterResult(nodes=(retail, candidate), edges=(edges[0],)),
        rows_by_offset=MappingProxyType({0x234: row}),
        stack_slot_localizer=None,
        target_assembly=(expected.raw,),
        current_assembly=(current.raw,),
        expected_assembly_digest="b" * 64,
    )
    backend = BackendEvidence(
        result=AdapterResult(nodes=tuple(nodes[2:-1]), edges=tuple(edges[1:])),
        pcdump_text="",
        role_compile={0: descriptors},
        nodes_by_class_ig=MappingProxyType(nodes_by_class_ig),
        nodes_by_virtual=MappingProxyType(
            {("r", def_ig): virtual_def.record_id, ("r", use_ig): virtual_use.record_id}
        ),
    )
    frame = FrameEvidence(
        result=AdapterResult(nodes=(stack,)),
        expected_stack_roles=MappingProxyType({"row": (32, 36)}),
        current_stack_nodes=MappingProxyType({"row": stack.record_id}),
    )
    bundle = SimpleNamespace(
        label=label,
        compile_id=compile_id,
        manifest=SimpleNamespace(function="fn_test"),
    )
    return FrontierGraph(
        bundle=bundle,
        store=store,
        checkdiff=checkdiff,
        backend=backend,
        inspector=AdapterResult(),
        frame=frame,
        source=SourceEvidence(
            result=AdapterResult(),
            expressions_by_signature=MappingProxyType({}),
            inline_scopes_by_callee=MappingProxyType({}),
        ),
        warnings=(),
    )


def graphs(*labels: str, missing_use: str | None = None, reused_register: bool = False) -> tuple[FrontierGraph, ...]:
    labels = labels or ("direct", "paired")
    return tuple(
        _graph(label, missing_use=label == missing_use, reused_register=reused_register)
        for label in labels
    )


def test_anchor_0234_derives_def_and_use_roles() -> None:
    alignment = align_anchor(graphs(), retail_offset=0x234, assertions=())
    assert [(role.kind, role.position, role.expected_phys) for role in alignment.operand_roles] == [
        ("def", 0, 22),
        ("use", 0, 21),
    ]


def test_role_matcher_does_not_select_later_reused_r22_node() -> None:
    alignment = align_anchor(graphs(reused_register=True), retail_offset=0x234, assertions=())
    row_def = alignment.by_operand["def:0"]
    assert row_def.right.attributes["first_def_signature"] == "addi r#,r#,0"
    assert row_def.right.attributes["ig_id"] == 66
    assert row_def.right.attributes["ig_id"] != 58


def test_effect_direction_is_independent_of_cli_order() -> None:
    forward_graphs = graphs("paired", "direct")
    reverse_graphs = graphs("direct", "paired")
    forward = derive_effects(align_anchor(forward_graphs, 0x234, ()), forward_graphs)
    reverse = derive_effects(align_anchor(reverse_graphs, 0x234, ()), reverse_graphs)
    assert forward == reverse
    assert forward.allocator_effects[0].direction == "first-exact-second-mismatch"


def test_unresolved_operand_does_not_drop_resolved_operand() -> None:
    pair = graphs(missing_use="paired")
    result = derive_effects(align_anchor(pair, 0x234, ()), pair)
    assert [effect.operand_key for effect in result.allocator_effects] == ["def:0"]
    assert result.abstentions[0].operand_key == "use:0"


def test_assertion_rejects_operand_not_present_on_retail_anchor() -> None:
    with pytest.raises(ValueError, match="operand"):
        align_anchor(graphs(), 0x234, ("direct:def:9=0:40",))


def test_reachable_stack_effect_creates_only_crossed_exact_mismatch_pair() -> None:
    pair = graphs()
    result = derive_effects(align_anchor(pair, 0x234, ()), pair)
    assert [(effect.role_key, effect.direction) for effect in result.stack_effects] == [
        ("row", "first-mismatch-second-exact")
    ]
    assert [pair.allocator.operand_key for pair in result.pairs] == ["def:0", "use:0"]
    assert {pair.allocator_exact_stack_mismatch_label for pair in result.pairs} == {"direct"}
    assert {pair.allocator_mismatch_stack_exact_label for pair in result.pairs} == {"paired"}


def test_graph_deltas_are_analysis_scoped_comparisons_not_cross_compile_edges() -> None:
    pair = graphs(reused_register=True)
    alignment = align_anchor(pair, 0x234, ())
    comparisons = build_role_comparisons(alignment, pair)
    deltas = diff_frontiers(pair, comparisons)
    assert {record.relation_kind for record in deltas} >= {"node-added", "node-changed"}
    assert all(record.analysis_id == alignment.analysis_id for record in deltas)
    assert all(not isinstance(record, EvidenceEdge) for record in deltas)


def test_graph_delta_aligns_expected_and_current_stack_nodes_separately() -> None:
    pair = graphs()
    for graph in pair:
        expected = _node(
            graph.bundle.compile_id,
            "stack-object",
            "row-stack-expected",
            {"side": "expected", "start": 32, "end": 36, "size": 4},
            role_key="row",
        )
        graph.store.add_nodes((expected,))
    alignment = align_anchor(pair, 0x234, ())
    deltas = diff_frontiers(pair, build_role_comparisons(alignment, pair))
    stack_changes = [
        record
        for record in deltas
        if record.relation_kind == "node-changed" and record.attributes.get("kind") == "stack-object"
    ]
    assert len(stack_changes) == 1
