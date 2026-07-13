from __future__ import annotations

import hashlib
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest

from src.mwcc_debug import role_descriptor
from src.mwcc_debug.causal_diff.alignment import (
    _canonical_owner_alternatives,
    _normalized_instruction,
    _rejection_summary,
    align_anchor,
    build_role_comparisons,
)
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
    ComparisonRecord,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
    min_confidence,
)
from src.mwcc_debug.causal_diff.owner_certificate import (
    OwnerCertificateRejection,
    OwnerCertificateResult,
    OwnerResolutionStatus,
    OwnerRoleKey,
    OwnerRoleResolution,
)
from src.mwcc_debug.causal_diff.source_adapter import SourceEvidence
from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore

OWNER_ROLE = OwnerRoleKey("use:0", "gpr", "row-home", 4, "locals")


def _only(items):
    values = tuple(items)
    assert len(values) == 1
    return values[0]


def _owner_fixtures():
    from tests import owner_certificate_fixtures

    return owner_certificate_fixtures


def _provenance(*input_record_ids: str) -> Provenance:
    return Provenance(
        artifact_sha256="a" * 64,
        parser="causal-alignment-test.v1",
        raw_start=None,
        raw_end=None,
        derivation_rule="unit-test-evidence",
        input_record_ids=tuple(input_record_ids),
    )


def test_normalized_instruction_treats_addi_zero_as_register_copy() -> None:
    assert _normalized_instruction("addi", "r22,r21,0") == _normalized_instruction("mr", "r64,r53")
    assert _normalized_instruction("addi", "r#,r#,0") == "mr r#,r#"


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
    confidence: Confidence = Confidence.DERIVED_UNIQUE,
) -> EvidenceEdge:
    return EvidenceEdge.create(
        compile_id=compile_id,
        function="fn_test",
        kind=kind,
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=confidence,
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


def _graph(
    label: str,
    *,
    missing_use: bool = False,
    reused_register: bool = False,
    opcode: str = "addi",
    heuristic_role: str | None = None,
    fixed_address_base: bool = False,
    absent_stack: bool = False,
) -> FrontierGraph:
    compile_id = hashlib.sha256(label.encode()).hexdigest()
    def_ig, use_ig = (40, 41) if label == "direct" else (66, 67)
    current_regs = (("r", 22), ("r", 21)) if label == "direct" else (("r", 20), ("r", 19))
    expected_regs = (("r", 22), ("r", 0 if fixed_address_base else 21))
    if fixed_address_base:
        current_regs = (current_regs[0], ("r", 0))

    def operands(regs: tuple[tuple[str, int], ...], *, virtual: bool = False) -> str:
        first = def_ig if virtual else regs[0][1]
        second = use_ig if virtual else regs[1][1]
        if opcode == "stwu":
            return f"r{first},-32(r{second})"
        if opcode in {"lwz", "lhz"}:
            return f"r{first},0(r{second})"
        return f"r{first},r{second},0"

    expected = CheckdiffInstruction(
        offset=0x234,
        opcode=opcode,
        operands=operands(expected_regs),
        regs=expected_regs,
        raw=f"+234: {opcode} {operands(expected_regs)}",
    )
    current = CheckdiffInstruction(
        offset=0x234,
        opcode=opcode,
        operands=operands(current_regs),
        regs=current_regs,
        raw=f"+234: {opcode} {operands(current_regs)}",
    )
    row = CheckdiffRow(offset=0x234, expected=expected, current=current)

    retail = _node(
        compile_id,
        "retail-instruction",
        "retail",
        {
            "offset": 0x234,
            "opcode": opcode,
            "operands": expected.operands,
            "regs": expected.regs,
            "neighborhood_signature": (f"{opcode} r#,r#,0",),
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
            "opcode": opcode,
            "operands": current.operands,
            "regs": current.regs,
            "retail_neighborhood_signature": (f"{opcode} r#,r#,0",),
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
            "opcode": opcode,
            "operands": operands(current_regs, virtual=True),
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
    backend_nodes = [occurrence, virtual_def, virtual_use, allocator_def, allocator_use]
    nodes = [retail, candidate, *backend_nodes]
    if not absent_stack:
        nodes.append(stack)
    edges = [
        _edge(compile_id, "aligns-to-retail", candidate, retail, attributes={"retail_offset": 0x234}),
        _edge(compile_id, "maps-to-allocator-node", virtual_def, allocator_def),
        _edge(compile_id, "maps-to-allocator-node", virtual_use, allocator_use),
    ]
    if not absent_stack:
        edges.append(_edge(compile_id, "materializes-as-stack-object", allocator_def, stack))
    semantic_roles = (
        (("use",), ("def", "use"))
        if opcode == "stwu"
        else (("def",), ("use",))
        if opcode in {"addi", "lwz", "lhz"}
        else (("use",), ("use",))
    )
    virtual_nodes = (virtual_def, virtual_use)
    for raw_position, roles in enumerate(semantic_roles):
        for semantic_role in roles:
            if missing_use and semantic_role == "use" and raw_position == 1:
                continue
            edges.append(
                _edge(
                    compile_id,
                    "defines-virtual" if semantic_role == "def" else "uses-virtual",
                    occurrence,
                    virtual_nodes[raw_position],
                    attributes={"operand_position": raw_position},
                    confidence=(Confidence.HEURISTIC if heuristic_role == semantic_role else Confidence.DERIVED_UNIQUE),
                )
            )

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
        backend_nodes.append(reused)
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
        result=AdapterResult(nodes=tuple(backend_nodes), edges=tuple(edges[1:])),
        pcdump_text="",
        role_compile={0: descriptors},
        nodes_by_class_ig=MappingProxyType(nodes_by_class_ig),
        nodes_by_virtual=MappingProxyType({("r", def_ig): virtual_def.record_id, ("r", use_ig): virtual_use.record_id}),
    )
    frame = FrameEvidence(
        result=AdapterResult(nodes=(() if absent_stack else (stack,))),
        expected_stack_roles=MappingProxyType({"row": (32, 36)}),
        current_stack_nodes=MappingProxyType({} if absent_stack else {"row": stack.record_id}),
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


def graphs(
    *labels: str,
    missing_use: str | None = None,
    reused_register: bool = False,
    opcode: str = "addi",
    heuristic_role: str | None = None,
    fixed_address_base: bool = False,
    absent_stack: str | None = None,
) -> tuple[FrontierGraph, ...]:
    labels = labels or ("direct", "paired")
    return tuple(
        _graph(
            label,
            missing_use=label == missing_use,
            reused_register=reused_register,
            opcode=opcode,
            heuristic_role=heuristic_role,
            fixed_address_base=fixed_address_base,
            absent_stack=label == absent_stack,
        )
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


def test_unsupported_opcode_semantics_abstain_before_role_correspondence() -> None:
    alignment = align_anchor(graphs(opcode="mystery"), 0x234, ())
    assert alignment.comparisons == ()
    assert {item.reason.value for item in alignment.abstentions} == {"unsupported-opcode-semantics"}


def test_heuristic_local_chain_is_cited_and_never_laundered_to_derived_unique() -> None:
    alignment = align_anchor(graphs(heuristic_role="def"), 0x234, ())
    comparison = alignment.by_operand["def:0"].comparison
    assert comparison.confidence is Confidence.HEURISTIC
    assert len(comparison.provenance.input_record_ids) == 12
    assert alignment.by_operand["use:0"].comparison.confidence is Confidence.DERIVED_UNIQUE


def test_update_form_orders_definition_before_uses() -> None:
    alignment = align_anchor(graphs(opcode="stwu"), 0x234, ())
    assert [(role.key, role.expected_phys) for role in alignment.operand_roles] == [
        ("def:0", 21),
        ("use:0", 22),
        ("use:1", 21),
    ]


def test_fixed_zero_address_base_is_not_an_allocator_operand() -> None:
    alignment = align_anchor(graphs(opcode="lwz", fixed_address_base=True), 0x234, ())
    assert [(role.key, role.expected_phys) for role in alignment.operand_roles] == [("def:0", 22)]


def test_r0_in_ordinary_register_field_remains_allocatable() -> None:
    alignment = align_anchor(graphs(opcode="mr", fixed_address_base=True), 0x234, ())
    assert [(role.key, role.expected_phys) for role in alignment.operand_roles] == [
        ("def:0", 22),
        ("use:0", 0),
    ]


def test_multiple_current_stack_candidates_abstain_instead_of_looking_absent() -> None:
    pair = list(graphs())
    direct = pair[0]
    duplicate = _node(
        direct.bundle.compile_id,
        "stack-object",
        "row-stack-duplicate",
        {"side": "current", "start": 40, "end": 44, "size": 4},
        role_key="row",
    )
    direct.store.add_nodes((duplicate,))
    pair[0] = replace(
        direct,
        frame=replace(direct.frame, current_stack_nodes=MappingProxyType({})),
    )
    result = derive_effects(align_anchor(pair, 0x234, ()), pair)
    assert result.stack_effects == ()
    assert result.pairs == ()
    abstention = next(item for item in result.abstentions if item.operand_key == "row")
    assert abstention.reason.value == "ambiguous-stack-object"
    assert len(abstention.missing_record_ids) == 2


def test_verified_zero_stack_candidates_uses_absent_object_mismatch() -> None:
    pair = graphs(absent_stack="direct")
    result = derive_effects(align_anchor(pair, 0x234, ()), pair)
    assert [(effect.role_key, effect.direction) for effect in result.stack_effects] == [
        ("row", "first-mismatch-second-exact")
    ]
    assert result.pairs


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


def test_added_material_node_emits_incident_edge_added_delta() -> None:
    pair = graphs()
    right = pair[1]
    added = _node(
        right.bundle.compile_id,
        "allocator-node",
        "added-ig",
        {"class_id": 0, "ig_id": 99, "assigned_reg": 18},
    )
    right_root = right.store.get_node(right.backend.nodes_by_class_ig[(0, 66)])
    assert right_root is not None
    incident = _edge(right.bundle.compile_id, "interferes-with", added, right_root)
    right.store.add_nodes((added,))
    right.store.add_edges((incident,))
    alignment = align_anchor(pair, 0x234, ())
    deltas = diff_frontiers(pair, build_role_comparisons(alignment, pair))
    assert any(
        record.relation_kind == "edge-added" and record.right_record_id == incident.record_id for record in deltas
    )


def test_removed_material_node_emits_incident_edge_removed_delta() -> None:
    pair = graphs()
    left = pair[0]
    removed = _node(
        left.bundle.compile_id,
        "allocator-node",
        "removed-ig",
        {"class_id": 0, "ig_id": 98, "assigned_reg": 17},
    )
    left_root = left.store.get_node(left.backend.nodes_by_class_ig[(0, 40)])
    assert left_root is not None
    incident = _edge(left.bundle.compile_id, "interferes-with", removed, left_root)
    left.store.add_nodes((removed,))
    left.store.add_edges((incident,))
    alignment = align_anchor(pair, 0x234, ())
    deltas = diff_frontiers(pair, build_role_comparisons(alignment, pair))
    assert any(
        record.relation_kind == "edge-removed" and record.left_record_id == incident.record_id for record in deltas
    )


@pytest.mark.parametrize(
    ("left_status", "right_status", "reason"),
    [
        ("missing", "unique", "backend-owner-missing"),
        ("ambiguous", "unique", "backend-owner-ambiguous"),
        ("contradictory", "unique", "backend-owner-contradictory"),
        ("incomplete", "unique", "backend-owner-path-incomplete"),
    ],
)
def test_nonunique_bilateral_resolution_emits_one_abstention(
    left_status: str,
    right_status: str,
    reason: str,
) -> None:
    fixtures = _owner_fixtures()
    comparisons = build_role_comparisons(
        fixtures.alignment(),
        fixtures.graphs_with_statuses(left_status, right_status),
    )
    abstention = _only(
        comparison for comparison in comparisons if comparison.relation_kind == "backend-owner-abstained"
    )
    assert abstention.attributes["reason"] == reason
    assert abstention.attributes["left_status"] == left_status
    assert abstention.attributes["right_status"] == right_status


@pytest.mark.parametrize(
    ("left_status", "right_status", "reason"),
    [
        ("ambiguous", "contradictory", "backend-owner-contradictory"),
        ("ambiguous", "incomplete", "backend-owner-path-incomplete"),
        ("ambiguous", "missing", "backend-owner-ambiguous"),
    ],
)
def test_bilateral_abstention_reason_uses_closed_priority(
    left_status: str,
    right_status: str,
    reason: str,
) -> None:
    fixtures = _owner_fixtures()
    abstention = _only(
        comparison
        for comparison in build_role_comparisons(
            fixtures.alignment(),
            fixtures.graphs_with_statuses(left_status, right_status),
        )
        if comparison.relation_kind == "backend-owner-abstained"
    )
    assert abstention.attributes["reason"] == reason


def test_unique_pair_uses_certificate_endpoints_and_minimum_confidence() -> None:
    fixtures = _owner_fixtures()
    graph_pair = fixtures.future_complete_graph_pair()
    comparison = _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), graph_pair)
        if item.relation_kind == "backend-owner-corresponds-to"
    )
    left = fixtures.node(comparison.left_record_id)
    right = fixtures.node(comparison.right_record_id)

    assert comparison.provenance.parser == "causal-backend-owner-alignment.v2"
    assert left.kind == right.kind == "owner-proof-certificate"
    assert comparison.confidence == min_confidence(left.confidence, right.confidence)
    assert set(comparison.provenance.input_record_ids) == {left.record_id, right.record_id}
    assert comparison.attributes == {"role": OWNER_ROLE.as_json()}


def test_owner_correspondence_requires_both_certificates_at_requested_anchor() -> None:
    fixtures = _owner_fixtures()
    graph_pair = fixtures.future_complete_graph_pair()
    mismatched_alignment = replace(
        fixtures.alignment(),
        retail_offset=fixtures.alignment().retail_offset + 4,
    )

    comparisons = build_role_comparisons(mismatched_alignment, graph_pair)

    assert not any(item.relation_kind == "backend-owner-corresponds-to" for item in comparisons)
    abstention = _only(item for item in comparisons if item.relation_kind == "backend-owner-abstained")
    assert abstention.attributes["left_status"] == "missing"
    assert abstention.attributes["right_status"] == "missing"


def test_owner_comparisons_ignore_roles_absent_from_requested_operands() -> None:
    fixtures = _owner_fixtures()
    alignment = replace(fixtures.alignment(), by_operand={})

    comparisons = build_role_comparisons(alignment, fixtures.future_complete_graph_pair())

    assert not any(
        item.relation_kind in {"backend-owner-corresponds-to", "backend-owner-abstained"} for item in comparisons
    )


def test_abstention_is_permutation_stable_and_binds_alternative_content() -> None:
    fixtures = _owner_fixtures()
    graph_pair = fixtures.graphs_with_statuses("ambiguous", "unique")
    forward = _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), graph_pair)
        if item.relation_kind == "backend-owner-abstained"
    )
    reverse = _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), tuple(reversed(graph_pair)))
        if item.relation_kind == "backend-owner-abstained"
    )
    changed = _only(
        item
        for item in build_role_comparisons(
            fixtures.alignment(),
            fixtures.graphs_with_statuses("contradictory", "unique"),
        )
        if item.relation_kind == "backend-owner-abstained"
    )

    assert forward == reverse
    assert fixtures.canonical_result(forward.attributes) == fixtures.canonical_result(reverse.attributes)
    assert forward.record_id == reverse.record_id
    assert forward.attributes["alternatives"] == reverse.attributes["alternatives"]
    assert forward.record_id != changed.record_id
    assert forward.provenance.derivation_rule.startswith("certified-owner-abstention:")


def test_exact_duplicate_rejection_summaries_collapse_with_multiplicity() -> None:
    fixtures = _owner_fixtures()
    left, _right = fixtures.graphs_with_statuses("contradictory", "unique")
    result = left.backend.owner_certificates
    assert result.is_trusted is True
    rejection = _only(result.resolution_for(OWNER_ROLE).rejections)
    other = replace(
        rejection,
        rejection_id="other-rejection",
        candidate_record_ids=(*rejection.candidate_record_ids, "other-candidate"),
    )
    summary = _rejection_summary("left", rejection)
    other_summary = _rejection_summary("left", other)

    alternatives = tuple(
        _canonical_owner_alternatives(raw)
        for raw in (
            (summary, other_summary, summary),
            (summary, other_summary, summary)[::-1],
        )
    )

    rejection_alternative = _only(item for item in alternatives[0] if item["rejection_id"] == rejection.rejection_id)
    assert rejection_alternative["multiplicity"] == 2
    assert alternatives[0] == alternatives[1]
    assert fixtures.canonical_result(alternatives[0]) == fixtures.canonical_result(alternatives[1])


class _ExplodingGlobalRejections:
    def __bool__(self) -> bool:
        raise AssertionError("untrusted global rejections tested for truth")

    def __iter__(self):
        raise AssertionError("untrusted global rejections iterated")

    def __len__(self) -> int:
        raise AssertionError("untrusted global rejections measured")

    def __getitem__(self, index: object) -> object:
        raise AssertionError(f"untrusted global rejections indexed: {index!r}")


class _ExplodingGlobalRejection:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"untrusted global rejection member accessed: {name}")


def _one_owner_abstention(graph_pair) -> ComparisonRecord:
    fixtures = _owner_fixtures()
    return _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), graph_pair)
        if item.relation_kind == "backend-owner-abstained"
    )


def _with_untrusted_owner_payload(
    graph_pair,
    *,
    construction: str,
    global_rejections: object,
):
    left, right = graph_pair
    trusted = left.backend.owner_certificates
    if construction == "direct":
        untrusted = OwnerCertificateResult(
            trusted.certificate_nodes,
            trusted.role_resolutions,
            global_rejections,  # type: ignore[arg-type]
        )
    elif construction == "replace":
        untrusted = replace(
            trusted,
            global_rejections=global_rejections,  # type: ignore[arg-type]
        )
    else:
        raise ValueError(f"unknown construction: {construction}")
    assert untrusted.is_trusted is False
    return (
        replace(left, backend=replace(left.backend, owner_certificates=untrusted)),
        right,
    )


@pytest.mark.parametrize("construction", ("direct", "replace"))
@pytest.mark.parametrize(
    "payload",
    (
        pytest.param(_ExplodingGlobalRejections(), id="exploding-container"),
        pytest.param((_ExplodingGlobalRejection(),), id="exploding-member"),
    ),
)
def test_untrusted_owner_payload_is_never_read_during_bilateral_abstention(
    construction: str,
    payload: object,
) -> None:
    fixtures = _owner_fixtures()
    graph_pair = _with_untrusted_owner_payload(
        fixtures.future_complete_graph_pair(),
        construction=construction,
        global_rejections=payload,
    )

    abstention = _one_owner_abstention(graph_pair)
    right_certificate = _only(graph_pair[1].backend.owner_certificates.certificate_nodes)

    assert abstention.attributes["reason"] == "backend-owner-path-incomplete"
    assert abstention.attributes["left_status"] == "incomplete"
    assert abstention.attributes["right_status"] == "unique"
    assert abstention.attributes["certificate_record_ids"]["left"] == ()
    assert abstention.attributes["rejections"]["left"] == ()
    assert not any(item["side"] == "left" for item in abstention.attributes["alternatives"])
    assert abstention.left_record_id is None
    assert abstention.right_record_id == right_certificate.record_id
    assert abstention.confidence is Confidence.HEURISTIC
    assert abstention.provenance.input_record_ids == (right_certificate.record_id,)


def test_untrusted_forged_rejections_cannot_change_abstention_content_or_id() -> None:
    fixtures = _owner_fixtures()
    forged = (
        OwnerCertificateRejection(
            "forged-a",
            "forged-reason-a",
            OWNER_ROLE,
            ("forged-candidate-a",),
            ("forged-support-a",),
        ),
        OwnerCertificateRejection(
            "forged-b",
            "forged-reason-b",
            None,
            ("forged-candidate-b",),
            ("forged-support-b",),
        ),
    )
    outputs = []
    for construction, payload in (
        ("direct", ()),
        ("direct", forged),
        ("direct", forged[::-1]),
        ("replace", forged),
        ("replace", forged[::-1]),
    ):
        graph_pair = _with_untrusted_owner_payload(
            fixtures.future_complete_graph_pair(),
            construction=construction,
            global_rejections=payload,
        )
        outputs.extend(_one_owner_abstention(ordered) for ordered in (graph_pair, tuple(reversed(graph_pair))))

    baseline = outputs[0]
    assert all(item == baseline for item in outputs)
    assert {item.record_id for item in outputs} == {baseline.record_id}
    assert {fixtures.canonical_result(item) for item in outputs} == {fixtures.canonical_result(baseline)}
    assert baseline.attributes["rejections"]["left"] == ()
    assert not any(item["side"] == "left" for item in baseline.attributes["alternatives"])


def test_trusted_builder_rejections_remain_in_abstention_audit_and_alternatives() -> None:
    fixtures = _owner_fixtures()
    graph_pair = fixtures.graphs_with_statuses("global-and-role-rejection", "unique")
    left_result = graph_pair[0].backend.owner_certificates
    assert left_result.is_trusted is True
    left_resolution = left_result.resolution_for(OWNER_ROLE)
    expected = tuple(
        sorted(
            (*left_resolution.rejections, *left_result.global_rejections),
            key=lambda item: item.rejection_id,
        )
    )

    forward = _one_owner_abstention(graph_pair)
    reverse = _one_owner_abstention(tuple(reversed(graph_pair)))
    actual = forward.attributes["rejections"]["left"]
    alternatives = tuple(
        item for item in forward.attributes["alternatives"] if item["side"] == "left" and item["kind"] == "rejection"
    )

    assert forward == reverse
    assert tuple(item["rejection_id"] for item in actual) == tuple(item.rejection_id for item in expected)
    assert tuple(item["reason"] for item in actual) == tuple(item.reason for item in expected)
    assert {item["rejection_id"] for item in alternatives} == {item.rejection_id for item in expected}
    assert all(item["multiplicity"] == 1 for item in alternatives)


def test_untrusted_certificate_result_can_only_abstain() -> None:
    fixtures = _owner_fixtures()
    left, right = fixtures.future_complete_graph_pair()
    trusted = left.backend.owner_certificates
    certificate = _only(trusted.certificate_nodes)
    untrusted = OwnerCertificateResult(
        (certificate,),
        (
            OwnerRoleResolution(
                OWNER_ROLE,
                OwnerResolutionStatus.UNIQUE,
                (certificate.record_id,),
                (),
            ),
        ),
        (),
    )
    left = replace(left, backend=replace(left.backend, owner_certificates=untrusted))

    abstention = _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), (left, right))
        if item.relation_kind == "backend-owner-abstained"
    )
    assert abstention.attributes["reason"] == "backend-owner-path-incomplete"
    assert abstention.attributes["left_status"] == "incomplete"


def test_unique_resolution_with_certificate_absent_from_store_abstains() -> None:
    fixtures = _owner_fixtures()
    left, right = fixtures.future_complete_graph_pair()
    without_certificate = InMemoryEvidenceStore()
    evidence = left.backend.object_bindings
    assert evidence is not None
    without_certificate.add_nodes(evidence.nodes)
    without_certificate.add_edges(evidence.edges)
    left = replace(left, store=without_certificate)

    abstention = _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), (left, right))
        if item.relation_kind == "backend-owner-abstained"
    )
    assert abstention.attributes["reason"] == "backend-owner-path-incomplete"
    assert abstention.left_record_id is None
    assert abstention.right_record_id is not None
    missing_id = _only(left.backend.owner_certificates.certificate_nodes).record_id
    assert any(item["certificate_record_id"] == missing_id for item in abstention.attributes["alternatives"])


@pytest.mark.parametrize(
    ("left_record_id", "right_record_id"),
    ((None, None), ("left", None), (None, "right"), ("left", "right")),
)
def test_backend_owner_abstention_is_the_nullable_endpoint_relation(
    left_record_id: str | None,
    right_record_id: str | None,
) -> None:
    comparison = ComparisonRecord(
        record_id="comparison",
        analysis_id="analysis",
        relation_kind="backend-owner-abstained",
        left_compile_id="left-compile",
        left_record_id=left_record_id,
        right_compile_id="right-compile",
        right_record_id=right_record_id,
        confidence=Confidence.HEURISTIC,
        provenance=_provenance(),
        attributes={},
    )
    assert comparison.left_record_id == left_record_id
    assert comparison.right_record_id == right_record_id


@pytest.mark.parametrize(
    "relation_kind",
    (
        "role-corresponds-to",
        "backend-owner-corresponds-to",
        "backend-owner-state-changed",
        "node-changed",
        "edge-changed",
        "node-added",
        "edge-added",
        "node-removed",
        "edge-removed",
    ),
)
def test_every_other_relation_rejects_two_nullable_endpoints(relation_kind: str) -> None:
    with pytest.raises(ValueError, match="invalid comparison endpoints"):
        ComparisonRecord(
            record_id="comparison",
            analysis_id="analysis",
            relation_kind=relation_kind,
            left_compile_id="left-compile",
            left_record_id=None,
            right_compile_id="right-compile",
            right_record_id=None,
            confidence=Confidence.HEURISTIC,
            provenance=_provenance(),
            attributes={},
        )


MALFORMED_OWNER_ROLES = (
    OwnerRoleKey("invalid", "gpr", "row-home", 4, "locals"),
    OwnerRoleKey("use:0", "vector", "row-home", 4, "locals"),
    OwnerRoleKey("use:0", "gpr", "INVALID_ROLE", 4, "locals"),
    OwnerRoleKey("use:0", "gpr", "row-home", True, "locals"),
    OwnerRoleKey("use:0", "gpr", "row-home", 4, "heap"),
    ("not", "an", "owner-role"),
)


@pytest.mark.parametrize("malformed_role", MALFORMED_OWNER_ROLES)
def test_untrusted_malformed_only_roles_are_ignored_without_validation(
    malformed_role: object,
) -> None:
    fixtures = _owner_fixtures()
    left, right = fixtures.graphs_with_statuses("missing", "missing")
    untrusted = OwnerCertificateResult(
        (),
        (
            OwnerRoleResolution(
                malformed_role,  # type: ignore[arg-type]
                OwnerResolutionStatus.MISSING,
                (),
                (),
            ),
        ),
        (),
    )
    left = replace(left, backend=replace(left.backend, owner_certificates=untrusted))

    comparisons = build_role_comparisons(fixtures.alignment(), (left, right))

    assert not any(item.relation_kind.startswith("backend-owner-") for item in comparisons)


@pytest.mark.parametrize("malformed_role", MALFORMED_OWNER_ROLES)
def test_trusted_other_side_role_abstains_without_reading_untrusted_roles(
    malformed_role: object,
) -> None:
    fixtures = _owner_fixtures()
    left, right = fixtures.graphs_with_statuses("missing", "unique")
    untrusted = OwnerCertificateResult(
        (),
        (
            OwnerRoleResolution(
                malformed_role,  # type: ignore[arg-type]
                OwnerResolutionStatus.MISSING,
                (),
                (),
            ),
        ),
        (),
    )
    left = replace(left, backend=replace(left.backend, owner_certificates=untrusted))

    abstention = _only(
        item
        for item in build_role_comparisons(fixtures.alignment(), (left, right))
        if item.relation_kind == "backend-owner-abstained"
    )

    assert abstention.attributes["role"] == OWNER_ROLE.as_json()
    assert abstention.attributes["left_status"] == "incomplete"
    assert abstention.attributes["right_status"] == "unique"


def test_trusted_results_are_looked_up_once_per_side_per_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = _owner_fixtures()
    graph_pair = fixtures.future_complete_graph_pair()
    trusted_ids = {id(graph.backend.owner_certificates): 0 for graph in graph_pair}
    original = OwnerCertificateResult.resolution_for

    def counted(result: OwnerCertificateResult, role: OwnerRoleKey):
        if id(result) in trusted_ids:
            trusted_ids[id(result)] += 1
        return original(result, role)

    monkeypatch.setattr(OwnerCertificateResult, "resolution_for", counted)

    build_role_comparisons(fixtures.alignment(), graph_pair)

    assert set(trusted_ids.values()) == {1}
