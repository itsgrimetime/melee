from __future__ import annotations

import json
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from src.mwcc_debug.causal_diff.alignment import RolePair
from src.mwcc_debug.causal_diff.canonical import stable_id
from src.mwcc_debug.causal_diff.effects import (
    AllocatorEffect,
    DerivedEffects,
    EffectPair,
    StackEffect,
)
from src.mwcc_debug.causal_diff.inference import (
    AnalysisStatus,
    AppliedRule,
    VerdictStatus,
    build_report,
    exit_code_for_report,
    infer_pair,
)
from src.mwcc_debug.causal_diff.models import (
    ComparisonRecord,
    Confidence,
    EvidenceEdge,
    EvidenceNode,
    Provenance,
)
from src.mwcc_debug.causal_diff.render import render_json, render_text
from src.mwcc_debug.causal_diff.store import EvidenceQuery, InMemoryEvidenceStore

ANALYSIS_ID = "a" * 64
LEFT_COMPILE = "b" * 64
RIGHT_COMPILE = "c" * 64


def _provenance(*record_ids: str) -> Provenance:
    return Provenance(
        artifact_sha256="d" * 64,
        parser="causal-inference-test.v1",
        raw_start=None,
        raw_end=None,
        derivation_rule="test-evidence",
        input_record_ids=record_ids,
    )


def _node(
    compile_id: str,
    kind: str,
    key: str,
    *,
    attributes: dict[str, object] | None = None,
) -> EvidenceNode:
    return EvidenceNode.create(
        compile_id=compile_id,
        function="fn_test",
        kind=kind,
        local_key=key,
        role_key=key,
        producer_confidence=Confidence.OBSERVED,
        adapter_confidence=Confidence.OBSERVED,
        provenance=_provenance(),
        attributes={} if attributes is None else attributes,
    )


def _edge(
    compile_id: str,
    kind: str,
    source: EvidenceNode,
    target: EvidenceNode,
    *,
    confidence: Confidence = Confidence.DERIVED_UNIQUE,
) -> EvidenceEdge:
    return EvidenceEdge.create(
        compile_id=compile_id,
        function="fn_test",
        kind=kind,
        source_id=source.record_id,
        target_id=target.record_id,
        occurrence_ordinal=0,
        producer_confidence=confidence,
        adapter_confidence=confidence,
        provenance=_provenance(source.record_id, target.record_id),
        input_confidences=(source.confidence, target.confidence),
        attributes={},
    )


def _comparison(
    relation: str,
    left: EvidenceNode,
    right: EvidenceNode,
    *,
    confidence: Confidence = Confidence.DERIVED_UNIQUE,
    attributes: dict[str, object] | None = None,
    ordinal: int = 0,
) -> ComparisonRecord:
    return ComparisonRecord.create(
        analysis_id=ANALYSIS_ID,
        relation_kind=relation,
        left_compile_id=left.compile_id,
        left_record_id=left.record_id,
        right_compile_id=right.compile_id,
        right_record_id=right.record_id,
        producer_confidence=confidence,
        adapter_confidence=confidence,
        provenance=_provenance(left.record_id, right.record_id),
        input_confidences=(left.confidence, right.confidence),
        attributes={} if attributes is None else attributes,
        occurrence_ordinal=ordinal,
    )


@dataclass(frozen=True, slots=True)
class InferenceCase:
    pair: EffectPair
    query: EvidenceQuery
    comparisons: tuple[ComparisonRecord, ...]
    effects: DerivedEffects


def _case(
    *,
    heuristic_path: bool = False,
    missing_owner_side: str | None = None,
    owner_relation: str = "node-changed",
    two_owners: bool = False,
    no_shared_path: bool = False,
    missing_anchor: bool = False,
    truncated: bool = False,
    contradictory: bool = False,
    expert_asserted: bool = False,
    role_confidence: Confidence | None = None,
    allocator_delta_confidence: Confidence = Confidence.DERIVED_UNIQUE,
    stack_delta_confidence: Confidence = Confidence.DERIVED_UNIQUE,
    unrelated_stack_edge_delta: bool = False,
) -> InferenceCase:
    store = InMemoryEvidenceStore()
    left_allocator = _node(LEFT_COMPILE, "allocator-node", "allocator-left")
    right_allocator = _node(RIGHT_COMPILE, "allocator-node", "allocator-right")
    left_stack = _node(LEFT_COMPILE, "stack-object", "stack-left", attributes={"start": 24})
    right_stack = _node(RIGHT_COMPILE, "stack-object", "stack-right", attributes={"start": 16})
    owner_attributes = {
        "traversal_truncated": truncated,
        "ownership_contradiction": contradictory,
    }
    left_owner = _node(
        LEFT_COMPILE,
        "source-expression",
        "owner-left",
        attributes=owner_attributes,
    )
    right_owner = _node(
        RIGHT_COMPILE,
        "source-expression",
        "owner-right",
        attributes=owner_attributes,
    )
    nodes = [left_allocator, left_stack, right_stack, left_owner, right_owner]
    if not missing_anchor:
        nodes.append(right_allocator)
    store.add_nodes(nodes)

    path_edges = [_edge(LEFT_COMPILE, "lowers-to", left_owner, left_allocator)]
    if not missing_anchor:
        path_edges.append(_edge(RIGHT_COMPILE, "lowers-to", right_owner, right_allocator))
    if not no_shared_path:
        path_edges.extend(
            [
                _edge(
                    LEFT_COMPILE,
                    "materializes-as-stack-object",
                    left_owner,
                    left_stack,
                    confidence=(Confidence.HEURISTIC if heuristic_path else Confidence.DERIVED_UNIQUE),
                ),
                *(
                    ()
                    if missing_owner_side == "right"
                    else (
                        _edge(
                            RIGHT_COMPILE,
                            "materializes-as-stack-object",
                            right_owner,
                            right_stack,
                        ),
                    )
                ),
            ]
        )
        if missing_owner_side == "left":
            path_edges = [
                edge
                for edge in path_edges
                if not (edge.source_id == left_owner.record_id and edge.target_id == left_stack.record_id)
            ]
    store.add_edges(path_edges)

    role_comparison = _comparison(
        "role-corresponds-to",
        left_allocator,
        right_allocator,
        confidence=(
            role_confidence
            if role_confidence is not None
            else Confidence.HEURISTIC
            if expert_asserted
            else Confidence.DERIVED_UNIQUE
        ),
        attributes={
            "operand_key": "def:0",
            "expert_assertion": expert_asserted,
            "verdict_cap": "candidate-cause" if expert_asserted else None,
        },
    )
    role_pair = RolePair(
        operand_key="def:0",
        left_label="direct",
        left=left_allocator,
        right_label="paired",
        right=right_allocator,
        comparison=role_comparison,
        asserted_labels=("paired",) if expert_asserted else (),
    )
    allocator_effect = AllocatorEffect(
        effect_id=stable_id(ANALYSIS_ID, "allocator-effect", "def:0"),
        operand_key="def:0",
        expected_phys=22,
        first_label="direct",
        first_phys=22,
        second_label="paired",
        second_phys=20,
        direction="first-exact-second-mismatch",
        role_correspondence=role_pair,
    )
    unrelated_left = _edge(LEFT_COMPILE, "lowers-to", left_owner, left_allocator)
    unrelated_right = _edge(RIGHT_COMPILE, "lowers-to", right_owner, right_allocator)
    stack_owner_record_ids = [left_stack.record_id, right_stack.record_id]
    if unrelated_stack_edge_delta:
        stack_owner_record_ids.extend((unrelated_left.record_id, unrelated_right.record_id))
    stack_effect = StackEffect(
        effect_id=stable_id(ANALYSIS_ID, "stack-effect", "row-home"),
        role_key="row-home",
        expected_offset=16,
        first_label="direct",
        first_offset=24,
        second_label="paired",
        second_offset=16,
        direction="first-mismatch-second-exact",
        owner_record_ids=tuple(stack_owner_record_ids),
    )
    pair = EffectPair(
        pair_id=stable_id(
            ANALYSIS_ID,
            "effect-pair",
            (allocator_effect.effect_id, stack_effect.effect_id),
        ),
        allocator=allocator_effect,
        stack=stack_effect,
        allocator_exact_stack_mismatch_label="direct",
        allocator_mismatch_stack_exact_label="paired",
    )
    if owner_relation == "node-added":
        owner_comparison = ComparisonRecord.create(
            analysis_id=ANALYSIS_ID,
            relation_kind="node-added",
            left_compile_id=LEFT_COMPILE,
            left_record_id=None,
            right_compile_id=RIGHT_COMPILE,
            right_record_id=right_owner.record_id,
            producer_confidence=Confidence.DERIVED_UNIQUE,
            adapter_confidence=Confidence.DERIVED_UNIQUE,
            provenance=_provenance(right_owner.record_id),
            input_confidences=(right_owner.confidence,),
            attributes={},
        )
    elif owner_relation == "node-removed":
        owner_comparison = ComparisonRecord.create(
            analysis_id=ANALYSIS_ID,
            relation_kind="node-removed",
            left_compile_id=LEFT_COMPILE,
            left_record_id=left_owner.record_id,
            right_compile_id=RIGHT_COMPILE,
            right_record_id=None,
            producer_confidence=Confidence.DERIVED_UNIQUE,
            adapter_confidence=Confidence.DERIVED_UNIQUE,
            provenance=_provenance(left_owner.record_id),
            input_confidences=(left_owner.confidence,),
            attributes={},
        )
    else:
        owner_comparison = _comparison("node-changed", left_owner, right_owner)
    stack_comparison = (
        _comparison("edge-changed", unrelated_left, unrelated_right, ordinal=2)
        if unrelated_stack_edge_delta
        else _comparison(
            "node-changed",
            left_stack,
            right_stack,
            confidence=stack_delta_confidence,
            ordinal=2,
        )
    )
    comparisons = [
        role_comparison,
        owner_comparison,
        _comparison(
            "node-changed",
            left_allocator,
            right_allocator,
            confidence=allocator_delta_confidence,
            ordinal=1,
        ),
        stack_comparison,
    ]

    if two_owners:
        left_second = _node(LEFT_COMPILE, "objobject", "second-owner-left")
        right_second = _node(RIGHT_COMPILE, "objobject", "second-owner-right")
        store.add_nodes((left_second, right_second))
        store.add_edges(
            (
                _edge(LEFT_COMPILE, "lowers-to", left_second, left_allocator),
                _edge(
                    LEFT_COMPILE,
                    "materializes-as-stack-object",
                    left_second,
                    left_stack,
                ),
                _edge(RIGHT_COMPILE, "lowers-to", right_second, right_allocator),
                _edge(
                    RIGHT_COMPILE,
                    "materializes-as-stack-object",
                    right_second,
                    right_stack,
                ),
            )
        )
        comparisons.append(_comparison("node-changed", left_second, right_second, ordinal=3))

    effects = DerivedEffects(
        allocator_effects=(allocator_effect,),
        stack_effects=(stack_effect,),
        pairs=(pair,),
        abstentions=(),
    )
    return InferenceCase(pair, store, tuple(comparisons), effects)


def proof_complete_unique() -> InferenceCase:
    return _case()


def complete_heuristic_path() -> InferenceCase:
    return _case(heuristic_path=True)


def complete_two_owner_paths() -> InferenceCase:
    return _case(two_owners=True)


def complete_no_shared_path() -> InferenceCase:
    return _case(no_shared_path=True)


def missing_anchor_identity() -> InferenceCase:
    return _case(missing_anchor=True)


def truncated_path() -> InferenceCase:
    return _case(truncated=True)


def contradictory_ownership() -> InferenceCase:
    return _case(contradictory=True)


def expert_asserted_complete_path() -> InferenceCase:
    return _case(expert_asserted=True)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (proof_complete_unique(), VerdictStatus.CAUSES),
        (complete_heuristic_path(), VerdictStatus.CANDIDATE_CAUSE),
        (complete_two_owner_paths(), VerdictStatus.CANDIDATE_CAUSE),
        (complete_no_shared_path(), VerdictStatus.NO_CAUSAL_DIFFERENCE),
        (missing_anchor_identity(), VerdictStatus.ABSTAIN),
        (truncated_path(), VerdictStatus.ABSTAIN),
        (contradictory_ownership(), VerdictStatus.ABSTAIN),
        (expert_asserted_complete_path(), VerdictStatus.CANDIDATE_CAUSE),
    ],
)
def test_normative_verdict_table(case: InferenceCase, expected: VerdictStatus) -> None:
    assert infer_pair(case.pair, case.query, case.comparisons).status is expected


@pytest.mark.parametrize(
    "case",
    (
        _case(missing_owner_side="left"),
        _case(missing_owner_side="right"),
        _case(owner_relation="node-added"),
        _case(owner_relation="node-removed"),
    ),
)
def test_shared_owner_requires_changed_endpoints_and_complete_bilateral_paths(
    case: InferenceCase,
) -> None:
    verdict = infer_pair(case.pair, case.query, case.comparisons)

    assert verdict.status is VerdictStatus.ABSTAIN
    assert "gate-3-shared-owner" in verdict.failed_gates


def test_proof_paths_include_owner_and_role_comparison_records() -> None:
    case = proof_complete_unique()
    verdict = infer_pair(case.pair, case.query, case.comparisons)
    owner_comparison = next(
        comparison
        for comparison in case.comparisons
        if comparison.relation_kind == "node-changed"
        and case.query.get_node(comparison.left_record_id or "").kind == "source-expression"
    )
    proof_members = {record_id for path in verdict.proof_paths for record_id in path}

    assert verdict.status is VerdictStatus.CAUSES
    assert len(verdict.proof_paths) == 4
    assert owner_comparison.record_id in proof_members
    assert case.pair.allocator.role_correspondence.comparison.record_id in proof_members


@pytest.mark.parametrize(
    ("case", "failed_gate"),
    (
        (
            _case(stack_delta_confidence=Confidence.HEURISTIC),
            "gate-5-stack-delta",
        ),
        (
            _case(allocator_delta_confidence=Confidence.HEURISTIC),
            "gate-4-allocator-delta",
        ),
        (
            _case(role_confidence=Confidence.HEURISTIC),
            "gate-2-backend-role-identity",
        ),
        (_case(heuristic_path=True), "gate-7-proof-capable-path"),
    ),
)
def test_complete_heuristic_evidence_caps_at_candidate(case: InferenceCase, failed_gate: str) -> None:
    verdict = infer_pair(case.pair, case.query, case.comparisons)

    assert verdict.status is VerdictStatus.CANDIDATE_CAUSE
    assert failed_gate in verdict.failed_gates


def test_unrelated_edge_delta_cannot_satisfy_stack_delta_gate() -> None:
    case = _case(unrelated_stack_edge_delta=True)

    verdict = infer_pair(case.pair, case.query, case.comparisons)

    assert verdict.status is VerdictStatus.ABSTAIN
    assert "gate-5-stack-delta" in verdict.failed_gates


@pytest.mark.parametrize("case", (complete_no_shared_path(), truncated_path()))
def test_every_verdict_states_operational_causality_scope(
    case: InferenceCase,
) -> None:
    verdict = infer_pair(case.pair, case.query, case.comparisons)

    assert verdict.recommendation.startswith("Operational compiler-evidence scope:")


def _graphs(
    case: InferenceCase,
    warnings: tuple[str, ...] = (),
    stores: tuple[EvidenceQuery, EvidenceQuery] | None = None,
) -> tuple[object, object]:
    manifest = SimpleNamespace(function="fn_test")
    left_store, right_store = stores or (case.query, case.query)
    return (
        SimpleNamespace(
            bundle=SimpleNamespace(label="direct", compile_id=LEFT_COMPILE, manifest=manifest),
            store=left_store,
            warnings=warnings,
        ),
        SimpleNamespace(
            bundle=SimpleNamespace(label="paired", compile_id=RIGHT_COMPILE, manifest=manifest),
            store=right_store,
            warnings=(),
        ),
    )


def _report_with(*statuses: VerdictStatus):
    case = proof_complete_unique()
    report = build_report(_graphs(case), case.effects, case.comparisons)
    verdicts = tuple(
        replace(
            report.verdicts[0],
            verdict_id=f"verdict-{index}",
            status=status,
        )
        for index, status in enumerate(statuses)
    )
    return replace(
        report,
        verdicts=verdicts,
        analysis_status=(
            AnalysisStatus.ABSTAINED
            if all(status is VerdictStatus.ABSTAIN for status in statuses)
            else AnalysisStatus.PARTIAL
            if any(status is VerdictStatus.ABSTAIN for status in statuses)
            else AnalysisStatus.COMPLETE
        ),
    )


def test_exit_aggregation_keeps_partial_success_at_zero() -> None:
    report = _report_with(VerdictStatus.CAUSES, VerdictStatus.ABSTAIN)
    assert report.analysis_status is AnalysisStatus.PARTIAL
    assert exit_code_for_report(report) == 0


def test_all_abstentions_exit_three() -> None:
    report = _report_with(VerdictStatus.ABSTAIN, VerdictStatus.ABSTAIN)
    assert report.analysis_status is AnalysisStatus.ABSTAINED
    assert exit_code_for_report(report) == 3


@pytest.mark.parametrize("collection", ("empty", "stack-only", "allocator-only"))
def test_complete_graph_without_eligible_pairs_reports_no_difference(
    collection: str,
) -> None:
    case = proof_complete_unique()
    effects = DerivedEffects(
        allocator_effects=(case.pair.allocator,) if collection == "allocator-only" else (),
        stack_effects=(case.pair.stack,) if collection == "stack-only" else (),
        pairs=(),
        abstentions=(),
    )

    report = build_report(_graphs(case), effects, case.comparisons)

    assert report.analysis_status is AnalysisStatus.COMPLETE
    assert tuple(verdict.status for verdict in report.verdicts) == (VerdictStatus.NO_CAUSAL_DIFFERENCE,)
    assert exit_code_for_report(report) == 0


def test_build_report_uses_effect_abstentions_for_partial_status() -> None:
    case = proof_complete_unique()
    abstention = SimpleNamespace(
        operand_key="use:0",
        reason=SimpleNamespace(value="missing-backend-role"),
        missing_capability_ids=("virtual-use-def",),
        missing_record_ids=(),
        follow_up_commands=("melee-agent debug inspect virtual-to-ig --help",),
    )
    effects = replace(case.effects, abstentions=(abstention,))
    report = build_report(_graphs(case, ("unknown inspector row",)), effects, case.comparisons)

    assert report.analysis_status is AnalysisStatus.PARTIAL
    assert report.missing_evidence == ("missing-backend-role:use:0", "virtual-use-def")
    assert report.warnings == ("unknown inspector row",)


def test_report_rendering_is_canonical_and_concise() -> None:
    case = proof_complete_unique()
    report = build_report(_graphs(case), case.effects, tuple(reversed(case.comparisons)))

    rendered = render_json(report)
    payload = json.loads(rendered)
    assert rendered.endswith("\n")
    assert payload["schema_version"] == "causal-diff-report.v1"
    assert [item["record_id"] for item in payload["comparisons"]] == sorted(
        item["record_id"] for item in payload["comparisons"]
    )
    text = render_text(report)
    assert text.startswith("causal-diff - fn_test\nstatus: complete\nCAUSES")
    verdict = report.verdicts[0]
    assert f"allocator: effect_id={case.pair.allocator.effect_id}" in text
    assert f"stack: effect_id={case.pair.stack.effect_id}" in text
    assert text.count("proof path ") == len(verdict.proof_paths)
    for path in verdict.proof_paths:
        assert " -> ".join(path) in text
    assert "melee-agent debug inspect" in text
    assert "full graph" not in text


def test_canonical_json_sorts_nested_semantic_collections() -> None:
    case = proof_complete_unique()
    report = build_report(_graphs(case), case.effects, case.comparisons)
    verdict = report.verdicts[0]
    allocator_second = replace(
        case.pair.allocator,
        effect_id="0" * 64,
        operand_key="use:9",
    )
    stack_second = replace(
        case.pair.stack,
        effect_id="1" * 64,
        role_key="other-home",
    )
    pair_second = replace(
        case.pair,
        pair_id="2" * 64,
        allocator=allocator_second,
        stack=stack_second,
    )
    effects_ordered = DerivedEffects(
        allocator_effects=tuple(
            sorted(
                (case.pair.allocator, allocator_second),
                key=lambda item: item.effect_id,
            )
        ),
        stack_effects=tuple(sorted((case.pair.stack, stack_second), key=lambda item: item.effect_id)),
        pairs=tuple(sorted((case.pair, pair_second), key=lambda item: item.pair_id)),
        abstentions=(),
    )
    paths_ordered = tuple(sorted(verdict.proof_paths))
    normalized_verdict = replace(
        verdict,
        proof_paths=paths_ordered,
        rejected_alternatives=("a", "z"),
        failed_gates=("gate-a", "gate-z"),
        follow_up_commands=("command-a", "command-z"),
    )
    rules = (
        AppliedRule("rule-a", ("a", "z"), ("out-a",)),
        AppliedRule("rule-z", ("b", "y"), ("out-z",)),
    )
    canonical = replace(
        report,
        effects=effects_ordered,
        verdicts=(normalized_verdict,),
        applied_rules=rules,
    )
    permuted = replace(
        canonical,
        effects=DerivedEffects(
            tuple(reversed(effects_ordered.allocator_effects)),
            tuple(reversed(effects_ordered.stack_effects)),
            tuple(reversed(effects_ordered.pairs)),
            (),
        ),
        verdicts=(
            replace(
                normalized_verdict,
                proof_paths=tuple(reversed(paths_ordered)),
                rejected_alternatives=("z", "a"),
                failed_gates=("gate-z", "gate-a"),
                follow_up_commands=("command-z", "command-a"),
            ),
        ),
        applied_rules=tuple(
            replace(
                rule,
                input_record_ids=tuple(reversed(rule.input_record_ids)),
                output_record_ids=tuple(reversed(rule.output_record_ids)),
            )
            for rule in reversed(rules)
        ),
    )

    assert render_json(canonical) == render_json(permuted)
    assert render_text(canonical) == render_text(permuted)
    payload = json.loads(render_json(permuted))
    assert payload["verdicts"][0]["proof_paths"] == [list(path) for path in paths_ordered]


def _compile_store(query: EvidenceQuery, compile_id: str) -> InMemoryEvidenceStore:
    store = InMemoryEvidenceStore()
    nodes = query.find_nodes(compile_id)
    store.add_nodes(nodes)
    store.add_edges(query.find_edges(compile_id))
    return store


def test_distinct_frontier_queries_render_identically() -> None:
    case = proof_complete_unique()
    shared = build_report(_graphs(case), case.effects, case.comparisons)
    distinct_graphs = _graphs(
        case,
        stores=(
            _compile_store(case.query, LEFT_COMPILE),
            _compile_store(case.query, RIGHT_COMPILE),
        ),
    )

    distinct = build_report(distinct_graphs, case.effects, case.comparisons)

    assert render_json(distinct) == render_json(shared)


def test_unrelated_compile_records_do_not_affect_owner_alternatives() -> None:
    case = proof_complete_unique()
    baseline = infer_pair(case.pair, case.query, case.comparisons)
    third = _node("e" * 64, "source-expression", "pollution-third")
    fourth = _node("f" * 64, "source-expression", "pollution-fourth")
    assert isinstance(case.query, InMemoryEvidenceStore)
    case.query.add_nodes((third, fourth))
    polluted_comparison = _comparison("node-changed", third, fourth, ordinal=99)

    polluted = infer_pair(
        case.pair,
        case.query,
        (*case.comparisons, polluted_comparison),
    )

    assert polluted.status is baseline.status
    assert polluted.proof_paths == baseline.proof_paths
    assert polluted.rejected_alternatives == baseline.rejected_alternatives


def test_invalid_evidence_metadata_forces_abstention() -> None:
    case = proof_complete_unique()
    cause_comparison = next(
        comparison
        for comparison in case.comparisons
        if comparison.relation_kind == "node-changed" and comparison.attributes.get("kind") is None
    )
    invalid = cause_comparison.with_attributes({"digest_valid": False})
    comparisons = tuple(invalid if item.record_id == cause_comparison.record_id else item for item in case.comparisons)

    verdict = infer_pair(case.pair, case.query, comparisons)
    assert verdict.status is VerdictStatus.ABSTAIN
    assert "gate-8-evidence-integrity" in verdict.failed_gates


def test_missing_role_comparison_record_forces_abstention() -> None:
    case = proof_complete_unique()
    comparisons = tuple(
        comparison for comparison in case.comparisons if comparison.relation_kind != "role-corresponds-to"
    )

    verdict = infer_pair(case.pair, case.query, comparisons)

    assert verdict.status is VerdictStatus.ABSTAIN
    assert verdict.failed_gates == ("gate-2-backend-role-identity",)


def test_global_identity_abstention_builds_report_without_comparisons() -> None:
    case = proof_complete_unique()
    abstention = SimpleNamespace(
        operand_key="anchor",
        reason=SimpleNamespace(value="missing-retail-row"),
        missing_capability_ids=(),
        missing_record_ids=(),
        follow_up_commands=("melee-agent debug inspect asm --help",),
    )
    effects = DerivedEffects((), (), (), (abstention,))

    report = build_report(_graphs(case), effects, ())

    assert report.analysis_id
    assert report.analysis_status is AnalysisStatus.ABSTAINED
    assert report.verdicts == ()
    assert exit_code_for_report(report) == 3
