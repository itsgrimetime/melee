from __future__ import annotations

import hashlib
import json
import re
import subprocess
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Mapping

import pytest

import src.search.delta_minimize.evaluator as evaluator_module
import src.search.delta_minimize.objectives as objectives_module
from src.mwcc_debug.coalesce_ir_facts import VirtualFacts
from src.mwcc_debug.colorgraph_profile import ColorGraphProfile
from src.mwcc_debug.parser import Block, Instruction
from src.mwcc_debug.role_descriptor import Compile, RoleDescriptor, build_descriptors, build_target_spec
from src.mwcc_debug.symbol_bridge import FirstDef
from src.search.delta_minimize.contracts import DeltaMinimizeError
from src.search.delta_minimize.delta import MaterializedCandidate
from src.search.delta_minimize.epochs import PARSER_SCHEMA_HASH
from src.search.delta_minimize.evaluator import (
    CandidateEvaluationConfig,
    EvaluationBackends,
    ParentEvidenceBundle,
    RawCandidateEvidence,
    capture_candidate,
    profile_candidate,
)
from src.search.delta_minimize.namespace_review import (
    NamespaceArtifact,
    NamespaceReviewRequest,
    ReviewedNamespaceBinding,
    ReviewedNamespaces,
)
from src.search.delta_minimize.objectives import (
    COLOR_TARGET_SCHEMA_V2,
    OBJECTIVE_MANIFEST_SCHEMA,
    ROLE_NAMESPACE_SCHEMA,
    AxisReference,
    NamespaceMapResolution,
    ObjectiveManifest,
    resolve_namespace_map,
)
from src.search.delta_minimize.store import DeltaRunStore

FIXTURES = Path(__file__).parents[2] / "fixtures" / "role_identity"
FUNCTION = "mnVibration_80248644"


def _candidate(tmp_path: Path, *, candidate_id: str = "candidate") -> MaterializedCandidate:
    source = tmp_path / f"{candidate_id}.c"
    source_text = "int candidate(void) { return 0; }\n"
    source.write_text(source_text, encoding="utf-8")
    return MaterializedCandidate(
        candidate_id,
        3,
        hashlib.sha256(source_text.encode()).hexdigest(),
        source,
        ("a", "b"),
    )


def _config(tmp_path: Path, *, include_objobjects: bool = True) -> CandidateEvaluationConfig:
    return CandidateEvaluationConfig(
        melee_root=tmp_path,
        function=FUNCTION,
        cflags_from=tmp_path / "unit.c",
        target_path=tmp_path / "target.json",
        output_dir=tmp_path / "scored",
        include_objobjects=include_objobjects,
        score_timeout=2.5,
        inspect_timeout=7,
    )


def _store(tmp_path: Path) -> DeltaRunStore:
    store = DeltaRunStore(tmp_path / "run")
    store.bind_provenance(
        {
            "cflags_hash": "cflags",
            "compiler_fingerprint": "compiler",
            "expected_object_hash": "object",
            "objective_manifest_hash": "objective",
            "parser_schema_hash": "parsers",
            "inspector_version": "inspector-v1;mode=objobjects",
        }
    )
    return store


def _score_row(candidate: MaterializedCandidate, pcdump: Path, **changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": candidate.candidate_id,
        "source_file": str(candidate.source_path),
        "pcdump_path": str(pcdump),
        "score_returncode": 0,
        "score_error_kind": None,
        "score_stderr": "",
        "checkdiff_evidence": {
            "function": FUNCTION,
            "match": False,
            "target_asm": ["+000: 38 60 00 00 li r3,0"],
            "current_asm": ["+000: 38 80 00 00 li r4,0"],
            "classification": {"primary": "register-allocation"},
        },
    }
    row.update(changes)
    return row


def test_capture_candidate_caches_fresh_evidence_and_reuses_it(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    calls = {"score": 0, "inspect": 0}

    def score_rows(rows, config):
        calls["score"] += 1
        assert rows[0]["source_retained"] == str(candidate.source_path)
        assert config.full_unit_source is True
        return [_score_row(candidate, pcdump)]

    def inspect_source(source: Path, function: str, output: Path, *, timeout: int):
        calls["inspect"] += 1
        assert (source, function, timeout) == (candidate.source_path, FUNCTION, 7)
        return "FUNCTION: mnVibration_80248644\nFrontend: OBJOBJECTS\n"

    store = _store(tmp_path)
    backends = EvaluationBackends(score_rows, inspect_source)
    first = capture_candidate(candidate, _config(tmp_path), backends=backends, store=store)
    second = capture_candidate(candidate, _config(tmp_path), backends=backends, store=store)

    assert second == first
    assert calls == {"score": 1, "inspect": 1}
    assert json.loads(json.dumps(first.to_dict())) == first.to_dict()


def test_token_equivalent_candidates_do_not_reuse_complete_inspection(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.c"
    first_text = "int candidate(void) {\n    return __LINE__;\n}\n"
    first_path.write_text(first_text, encoding="utf-8")
    first = MaterializedCandidate(
        "first",
        3,
        hashlib.sha256(first_text.encode()).hexdigest(),
        first_path,
        (),
    )
    second_path = tmp_path / "second.c"
    second_text = "\nint  candidate ( void )  {\n    return __LINE__ ;\n}\n"
    second_path.write_text(second_text, encoding="utf-8")
    second = MaterializedCandidate(
        "second",
        4,
        hashlib.sha256(second_text.encode()).hexdigest(),
        second_path,
        ("presentation",),
    )
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    calls = {"inspect": 0}

    def score_rows(rows, _config):
        candidate = first if rows[0]["candidate_id"] == "first" else second
        return [_score_row(candidate, pcdump)]

    def inspect_source(*_args, **_kwargs):
        calls["inspect"] += 1
        return (
            f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
            "ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: value\n"
            f"  Type: int\n  Scope: {FUNCTION}\n  Expression: value\n"
        )

    store = _store(tmp_path)
    backends = EvaluationBackends(score_rows, inspect_source)
    first_evidence = capture_candidate(first, _config(tmp_path), backends=backends, store=store)
    second_evidence = capture_candidate(second, _config(tmp_path), backends=backends, store=store)

    assert second_evidence.inspect_text == first_evidence.inspect_text
    assert calls == {"inspect": 2}


def test_default_inspector_uses_evaluation_repo_root(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "build" / "candidate.c"
    source.parent.mkdir()
    source.write_text("int f(void) { return 0; }\n", encoding="utf-8")
    output = tmp_path / "evidence" / "inspect.txt"
    captured = {}

    def fake_read(diff_input, *, function, melee_root, timeout, output_path):
        captured.update(
            function=function,
            melee_root=melee_root,
            timeout=timeout,
            output_path=output_path,
        )
        return "FUNCTION: f\nFrontend: OBJOBJECTS\n"

    monkeypatch.setattr(evaluator_module, "read_inspect_input_if_available", fake_read)

    text = evaluator_module._default_inspect_source(
        source,
        "f",
        output,
        timeout=180,
        melee_root=tmp_path,
    )

    assert text.startswith("FUNCTION: f")
    assert captured == {
        "function": "f",
        "melee_root": tmp_path,
        "timeout": 180,
        "output_path": output,
    }


def test_structural_status_uses_checkdiff_truth_gate() -> None:
    payload = {
        "match": False,
        "classification": {
            "primary": "register-allocation",
            "structural_truth_gate": {"status": "structural-match"},
        },
    }

    assert evaluator_module._structural_status(payload) == "structural-match"


def test_asm_lines_ignores_checkdiff_blank_terminator() -> None:
    assert evaluator_module._asm_lines(
        {"target_asm": ["+000: 38 60 00 00 li r3,0", ""]},
        "target_asm",
    ) == ["+000: 38 60 00 00 li r3,0"]


def _namespace_compile() -> Compile:
    return _with_complete_virtual_identity(_raw_namespace_compile())


def _review_namespace_compile() -> Compile:
    compile = _namespace_compile()
    coalesce = compile.fev.coalesce_sections[-1]
    simplify = compile.fev.simplify_sections[-1]
    added_virtuals = 110 - coalesce.n_virtuals
    coalesce.n_virtuals = 110
    coalesce.exit_n_virtuals = 110
    coalesce.distinct_roots += added_virtuals
    simplify.n_class_regs = 110
    return compile


def _raw_namespace_compile() -> Compile:
    text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    return Compile.from_text(text, FUNCTION, "")


def _with_complete_virtual_identity(compile: Compile) -> Compile:
    virtual_count = compile.fev.coalesce_sections[-1].n_virtuals
    for ig_idx in range(virtual_count):
        facts = VirtualFacts(
            virtual=ig_idx,
            first_def=FirstDef(
                block_idx=0,
                opcode=f"semantic_{ig_idx}",
                operands=f"r{ig_idx},r{ig_idx}",
                annotations=[],
                regs=[("r", ig_idx), ("r", ig_idx)],
            ),
            use_sites=[],
            use_sites_truncated=False,
            is_param=False,
            is_phys=False,
        )
        compile.ir_facts.by_reg[("r", ig_idx)] = facts
        compile.ir_facts.by_virtual[ig_idx] = facts
    return compile


def _namespace_descriptors(compile: Compile) -> dict[int, RoleDescriptor]:
    return {
        ig_idx: replace(
            descriptor,
            first_def_sig=f"ig:{ig_idx}:{descriptor.first_def_sig}",
        )
        for ig_idx, descriptor in build_descriptors(compile, 0).items()
    }


def test_structural_namespace_witness_excludes_allocator_outcome_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _namespace_compile()
    changed = deepcopy(baseline)
    baseline_descriptors = _namespace_descriptors(baseline)
    changed_descriptors = {
        ig_idx: replace(
            descriptor,
            assigned_reg=(descriptor.assigned_reg or 0) + 1,
            live_range=(100, 200),
            spilled=not descriptor.spilled,
        )
        for ig_idx, descriptor in baseline_descriptors.items()
    }
    decision = changed.fev.colorgraph_sections[-1].decisions[0]
    decision.assigned_reg = (decision.assigned_reg + 1) % 32
    decision.interferers = [(decision.ig_idx, decision.assigned_reg)]
    decision.n_interferers = len(decision.interferers)
    decision.flags ^= 1
    simplify = changed.fev.simplify_sections[-1].entries[0]
    simplify.flags ^= 8
    simplify.spilled = not simplify.spilled
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_descriptors",
        lambda compile, _class_id: (baseline_descriptors if compile is baseline else changed_descriptors),
    )

    baseline_witness = objectives_module._structural_namespace_witness(baseline, 0)
    changed_witness = objectives_module._structural_namespace_witness(changed, 0)

    assert baseline_witness == changed_witness
    assert baseline_witness is not None
    assert list(baseline_witness.items())[:2] == [
        ("schema_version", ROLE_NAMESPACE_SCHEMA),
        ("class_id", 0),
    ]


def test_structural_namespace_witness_covers_coalesced_virtual_identity() -> None:
    baseline = _namespace_compile()
    changed = deepcopy(baseline)
    decision_igs = set(_namespace_descriptors(baseline))
    coalesced_ig = next(
        alias for alias, _root in baseline.fev.coalesce_sections[-1].mappings if alias not in decision_igs
    )
    facts = changed.ir_facts.by_reg[("r", coalesced_ig)]
    assert facts.first_def is not None
    facts.first_def = replace(
        facts.first_def,
        opcode=f"changed_{facts.first_def.opcode}",
    )

    baseline_witness = objectives_module._structural_namespace_witness(baseline, 0)
    changed_witness = objectives_module._structural_namespace_witness(changed, 0)

    assert baseline_witness is None or changed_witness != baseline_witness


def test_structural_namespace_witness_covers_nondecision_use_operands() -> None:
    baseline = _namespace_compile()
    changed = deepcopy(baseline)
    decision_igs = set(_namespace_descriptors(baseline))
    coalesced_ig = next(
        alias for alias, _root in baseline.fev.coalesce_sections[-1].mappings if alias not in decision_igs
    )
    for compile, offset in ((baseline, 4), (changed, 8)):
        compile.ir_facts.by_reg[("r", coalesced_ig)].use_sites = [
            (
                0,
                Instruction(
                    opcode="stw",
                    operands=f"r{coalesced_ig},{offset}(r3)",
                    annotations=[],
                    regs=[("r", coalesced_ig), ("r", 3)],
                ),
            )
        ]

    baseline_witness = objectives_module._structural_namespace_witness(baseline, 0)
    changed_witness = objectives_module._structural_namespace_witness(changed, 0)

    assert baseline_witness is None or changed_witness != baseline_witness


def test_early_ir_identity_covers_virtuals_missing_from_late_pass() -> None:
    compile = _raw_namespace_compile()
    virtual_count = compile.fev.coalesce_sections[-1].n_virtuals
    assert set(compile.ir_facts.by_reg) < {("r", ig_idx) for ig_idx in range(virtual_count)}

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        compile,
        deepcopy(compile),
        0,
        virtual_count,
    )

    assert role_map is not None
    assert set(role_map) == set(range(virtual_count))


def test_early_ir_semantic_change_changes_full_identity() -> None:
    baseline = _raw_namespace_compile()
    changed = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    changed_instructions = [
        instruction
        for block in changed.fn.passes[0].blocks
        for instruction in block.instructions
        if ("r", 33) in instruction.regs
    ]
    assert len(changed_instructions) == 2
    for instruction in changed_instructions:
        instruction.operands = f"{instruction.operands}+semantic-change"

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        changed,
        0,
        virtual_count,
    )

    assert role_map is None


def test_pairwise_namespace_rejects_swapped_block_instruction_lists() -> None:
    baseline = _raw_namespace_compile()
    changed = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    semantic_pass = changed.fn.passes[0]
    blocks = {block.index: block for block in semantic_pass.blocks}
    blocks[5].instructions, blocks[6].instructions = (
        blocks[6].instructions,
        blocks[5].instructions,
    )

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        changed,
        0,
        virtual_count,
    )

    assert role_map is None


def test_pairwise_namespace_uses_canonical_identity_after_block_list_reorder() -> None:
    baseline = _raw_namespace_compile()
    reordered = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    reordered.fn.passes[0].blocks.reverse()

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        reordered,
        0,
        virtual_count,
    )

    assert role_map == {virtual: virtual for virtual in range(virtual_count)}


def _symmetric_diamond_compile() -> Compile:
    compile = _raw_namespace_compile()
    compile.fev.coalesce_sections[-1].n_virtuals = 34
    compile.fn.passes[0].blocks = [
        Block(index=0, pred=[], succ=[1, 2], labels=["entry"]),
        Block(
            index=1,
            pred=[0],
            succ=[3],
            labels=["left"],
            instructions=[
                Instruction("li", "r32,0", [], [("r", 32)]),
            ],
        ),
        Block(
            index=2,
            pred=[0],
            succ=[3],
            labels=["right"],
            instructions=[
                Instruction("li", "r33,0", [], [("r", 33)]),
            ],
        ),
        Block(index=3, pred=[1, 2], succ=[], labels=["exit"]),
    ]
    return compile


def test_pairwise_namespace_rejects_ambiguous_symmetric_block_pairing() -> None:
    baseline = _symmetric_diamond_compile()
    peer = deepcopy(baseline)

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        peer,
        0,
        34,
        {32: 32, 33: 33},
    )

    assert role_map is None


def test_pairwise_namespace_validates_seeded_role_second_occurrence() -> None:
    baseline = _raw_namespace_compile()
    changed = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    occurrences = [
        instruction
        for block in changed.fn.passes[0].blocks
        for instruction in block.instructions
        if ("r", 32) in instruction.regs
    ]
    assert len(occurrences) == 3
    occurrences[-1].operands = f"{occurrences[-1].operands}+semantic-change"

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        changed,
        0,
        virtual_count,
    )

    assert role_map is None


def test_pairwise_namespace_validates_zero_virtual_branch_target() -> None:
    baseline = _raw_namespace_compile()
    changed = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    block = next(block for block in changed.fn.passes[0].blocks if block.index == 3)
    branch = next(instruction for instruction in block.instructions if instruction.opcode == "bt")
    assert branch.regs == []
    assert branch.operands.endswith("B7")
    branch.operands = branch.operands.removesuffix("B7") + "B4"

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        changed,
        0,
        virtual_count,
    )

    assert role_map is None


def _reviewed_seed_compile() -> Compile:
    compile = _raw_namespace_compile()
    compile.fev.coalesce_sections[-1].n_virtuals = 61
    instructions = [
        Instruction("mr", f"r{virtual},r3", [], [("r", virtual), ("r", 3)])
        for virtual in range(32, 61)
        for _occurrence in range(2)
    ]
    compile.fn.passes[0].blocks = [
        Block(
            index=0,
            pred=[],
            succ=[],
            labels=["entry"],
            instructions=instructions,
        )
    ]
    return compile


def test_pairwise_namespace_rejects_unproved_full_reviewed_swap() -> None:
    baseline = _reviewed_seed_compile()
    peer = deepcopy(baseline)
    reviewed = {virtual: virtual for virtual in range(32, 61)}
    reviewed[55], reviewed[60] = reviewed[60], reviewed[55]

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        peer,
        0,
        61,
        reviewed,
    )

    assert role_map is None


def test_pairwise_namespace_separates_same_index_cross_class_dependencies() -> None:
    baseline = _raw_namespace_compile()
    baseline.fev.coalesce_sections[-1].n_virtuals = 35
    baseline.fn.passes[0].blocks = [
        Block(
            index=0,
            pred=[],
            succ=[],
            labels=["entry"],
            instructions=[
                Instruction("li", "r32,1", [], [("r", 32)]),
                Instruction("li", "r33,2", [], [("r", 33)]),
                Instruction("fmr", "f32,f1", [], [("f", 32), ("f", 1)]),
                Instruction("fmr", "f33,f2", [], [("f", 33), ("f", 2)]),
                Instruction("mix", "r34,r32,f32", [], [("r", 34), ("r", 32), ("f", 32)]),
            ],
        )
    ]
    changed = deepcopy(baseline)
    changed_instructions = changed.fn.passes[0].blocks[0].instructions
    changed_instructions[0].operands = "r33,1"
    changed_instructions[0].regs = [("r", 33)]
    changed_instructions[1].operands = "r32,2"
    changed_instructions[1].regs = [("r", 32)]
    changed_instructions[-1].operands = "r34,r33,f33"
    changed_instructions[-1].regs = [("r", 34), ("r", 33), ("f", 33)]

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        changed,
        0,
        35,
    )

    assert role_map is None


def test_early_ir_occurrences_prove_nonidentity_namespace_bijection() -> None:
    baseline = _raw_namespace_compile()
    peer = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    first_ig, second_ig = 47, 54
    for block in peer.fn.passes[0].blocks:
        for instruction in block.instructions:
            instruction.operands = re.sub(
                rf"\br({first_ig}|{second_ig})\b",
                lambda match: (f"r{second_ig}" if int(match.group(1)) == first_ig else f"r{first_ig}"),
                instruction.operands,
            )
            instruction.regs = [
                (
                    kind,
                    second_ig
                    if kind == "r" and number == first_ig
                    else first_ig
                    if kind == "r" and number == second_ig
                    else number,
                )
                for kind, number in instruction.regs
            ]

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        peer,
        0,
        virtual_count,
    )

    assert role_map is not None
    assert set(role_map) == set(range(virtual_count))
    assert role_map[first_ig] == second_ig
    assert role_map[second_ig] == first_ig


def test_pairwise_namespace_rejects_conflicting_reviewed_anchor() -> None:
    baseline = _raw_namespace_compile()
    peer = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        peer,
        0,
        virtual_count,
        {47: 54},
    )

    assert role_map is None


def test_pairwise_namespace_rejects_missing_early_ir_virtual() -> None:
    baseline = _raw_namespace_compile()
    peer = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    for block in peer.fn.passes[0].blocks:
        for instruction in block.instructions:
            instruction.operands = re.sub(r"\br47\b", "r3", instruction.operands)
            instruction.regs = [
                (kind, 3 if kind == "r" and number == 47 else number) for kind, number in instruction.regs
            ]

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        peer,
        0,
        virtual_count,
    )

    assert role_map is None


def test_pairwise_namespace_excludes_late_allocator_objective_state() -> None:
    baseline = _raw_namespace_compile()
    changed = deepcopy(baseline)
    virtual_count = baseline.fev.coalesce_sections[-1].n_virtuals
    decision = changed.fev.colorgraph_sections[-1].decisions[0]
    decision.assigned_reg = (decision.assigned_reg + 1) % 32
    decision.interferers = [(decision.ig_idx, decision.assigned_reg)]
    decision.n_interferers = 1
    changed.fev.simplify_sections[-1].entries.reverse()
    changed.fev.coalesce_sections[-1].mappings.reverse()

    role_map = objectives_module.role_descriptor.prove_virtual_namespace_map(
        baseline,
        changed,
        0,
        virtual_count,
    )

    assert role_map == {ig_idx: ig_idx for ig_idx in range(virtual_count)}


def _reviewed_resolution_context(
    domain: tuple[int, ...],
) -> tuple[NamespaceReviewRequest, ReviewedNamespaces]:
    request = NamespaceReviewRequest(
        function=FUNCTION,
        class_id=0,
        register_class="GPR",
        namespace_schema=ROLE_NAMESPACE_SCHEMA,
        parser_schema_hash=PARSER_SCHEMA_HASH,
        target_sha256="5" * 64,
        delta_manifest_sha256="6" * 64,
        left_source_sha256="1" * 64,
        right_source_sha256="3" * 64,
        cflags_hash="7" * 64,
        compiler_fingerprint="compiler-v1",
        expected_object_hash="8" * 64,
        inspector_version="inspector-v1",
        canonical_artifact_id="parent:left",
        canonical_source_sha256="1" * 64,
        canonical_pcdump_sha256="2" * 64,
        lattice_atom_count=3,
        reviewed_anchors={64: 64, 78: 78},
        artifacts=(
            NamespaceArtifact(
                artifact_id="parent:left",
                kind="parent",
                side="left",
                candidate=None,
                mask=None,
                source_sha256="1" * 64,
                pcdump_sha256="2" * 64,
                domain=domain,
                automatically_resolved=True,
                diagnostic=None,
            ),
            NamespaceArtifact(
                artifact_id="parent:right",
                kind="parent",
                side="right",
                candidate=None,
                mask=None,
                source_sha256="3" * 64,
                pcdump_sha256="4" * 64,
                domain=domain,
                automatically_resolved=False,
                diagnostic="ambiguous-automatic-v5",
            ),
        ),
    )
    reviewed = ReviewedNamespaces(
        request=request,
        request_sha256=request.sha256,
        bindings=(
            ReviewedNamespaceBinding(
                artifact_id="parent:right",
                source_sha256="3" * 64,
                pcdump_sha256="4" * 64,
                canonical_to_artifact={role: role for role in domain},
            ),
        ),
    )
    return request, reviewed


def test_namespace_resolver_inherits_only_exact_two_hash_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile = _review_namespace_compile()
    domain = tuple(range(110))
    inherited = NamespaceMapResolution(
        artifact_id="parent:left",
        source_sha256="1" * 64,
        pcdump_sha256="2" * 64,
        raw_to_canonical={role: role for role in domain},
        source="automatic-v5",
    )
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "prove_virtual_namespace_map",
        lambda *_args, **_kwargs: None,
    )

    exact = resolve_namespace_map(
        artifact_id="candidate:mask-000",
        source_sha256="1" * 64,
        pcdump_sha256="2" * 64,
        artifact_compile=compile,
        canonical_compile=compile,
        class_id=0,
        domain=domain,
        resolved=(inherited,),
    )
    pcdump_only = resolve_namespace_map(
        artifact_id="candidate:mask-001",
        source_sha256="9" * 64,
        pcdump_sha256="2" * 64,
        artifact_compile=compile,
        canonical_compile=compile,
        class_id=0,
        domain=domain,
        resolved=(inherited,),
    )

    assert exact.source == "inheritance"
    assert dict(exact.raw_to_canonical or {}) == dict(inherited.raw_to_canonical or {})
    assert pcdump_only.source == "unresolved"
    assert pcdump_only.raw_to_canonical is None


def test_namespace_resolver_automatic_v5_precedes_review_and_rejects_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile = _review_namespace_compile()
    domain = tuple(range(110))
    request, reviewed = _reviewed_resolution_context(domain)
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "prove_virtual_namespace_map",
        lambda *_args, **_kwargs: {role: role for role in domain},
    )

    with pytest.raises(DeltaMinimizeError, match="^automatic-reviewed-namespace-conflict$"):
        resolve_namespace_map(
            artifact_id="parent:right",
            source_sha256="3" * 64,
            pcdump_sha256="4" * 64,
            artifact_compile=compile,
            canonical_compile=compile,
            class_id=0,
            domain=domain,
            resolved=(),
            request=request,
            reviewed=reviewed,
        )

    automatic = resolve_namespace_map(
        artifact_id="candidate:mask-000",
        source_sha256="9" * 64,
        pcdump_sha256="a" * 64,
        artifact_compile=compile,
        canonical_compile=compile,
        class_id=0,
        domain=domain,
        resolved=(),
    )
    assert automatic.source == "automatic-v5"
    assert dict(automatic.raw_to_canonical or {}) == {role: role for role in domain}


def test_namespace_resolver_uses_reviewed_fallback_and_fails_closed_on_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile = _review_namespace_compile()
    domain = tuple(range(110))
    request, reviewed = _reviewed_resolution_context(domain)
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "prove_virtual_namespace_map",
        lambda *_args, **_kwargs: None,
    )

    reviewed_result = resolve_namespace_map(
        artifact_id="parent:right",
        source_sha256="3" * 64,
        pcdump_sha256="4" * 64,
        artifact_compile=compile,
        canonical_compile=compile,
        class_id=0,
        domain=domain,
        resolved=(),
        request=request,
        reviewed=reviewed,
    )
    incomplete = resolve_namespace_map(
        artifact_id="parent:right",
        source_sha256="3" * 64,
        pcdump_sha256="4" * 64,
        artifact_compile=compile,
        canonical_compile=compile,
        class_id=0,
        domain=domain,
        resolved=(),
        request=request,
    )

    assert reviewed_result.source == "reviewed-v1"
    assert dict(reviewed_result.raw_to_canonical or {}) == {role: role for role in domain}
    assert incomplete.source == "unresolved"
    with pytest.raises(DeltaMinimizeError, match="^reviewed-namespace-artifact-drift$"):
        resolve_namespace_map(
            artifact_id="parent:right",
            source_sha256="9" * 64,
            pcdump_sha256="4" * 64,
            artifact_compile=compile,
            canonical_compile=compile,
            class_id=0,
            domain=domain,
            resolved=(),
            request=request,
            reviewed=reviewed,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "virtual-count",
        "semantic-identity",
        "decision-traversal",
        "simplify-traversal",
        "coalesce-mapping",
    ),
)
def test_namespace_witness_uses_identity_not_objective_lanes(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    baseline = _namespace_compile()
    changed = deepcopy(baseline)
    baseline_descriptors = _namespace_descriptors(baseline)
    changed_descriptors = dict(baseline_descriptors)
    if mutation == "virtual-count":
        changed.fev.coalesce_sections[-1].n_virtuals += 1
    elif mutation == "semantic-identity":
        ig_idx = next(iter(changed_descriptors))
        facts = changed.ir_facts.by_reg[("r", ig_idx)]
        assert facts.first_def is not None
        facts.first_def = replace(
            facts.first_def,
            opcode=f"changed_{facts.first_def.opcode}",
        )
    elif mutation == "decision-traversal":
        first, second = changed.fev.colorgraph_sections[-1].decisions[:2]
        first.iter_idx, second.iter_idx = second.iter_idx, first.iter_idx
    elif mutation == "simplify-traversal":
        first, second = [row for row in changed.fev.simplify_sections[-1].entries if row.ig_idx >= 0][:2]
        first.iter_idx, second.iter_idx = second.iter_idx, first.iter_idx
    elif mutation == "coalesce-mapping":
        section = changed.fev.coalesce_sections[-1]
        section.mappings = list(reversed(section.mappings))
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_descriptors",
        lambda compile, _class_id: (baseline_descriptors if compile is baseline else changed_descriptors),
    )

    baseline_witness = objectives_module._structural_namespace_witness(baseline, 0)
    changed_witness = objectives_module._structural_namespace_witness(changed, 0)
    baseline_exact = objectives_module._allocator_namespace_witness(baseline, 0)
    changed_exact = objectives_module._allocator_namespace_witness(changed, 0)

    assert baseline_witness is not None
    assert baseline_exact is not None
    if mutation in {"virtual-count", "semantic-identity"}:
        assert changed_witness is None or changed_witness != baseline_witness
        assert changed_exact is None or changed_exact != baseline_exact
    else:
        assert changed_witness == baseline_witness
        assert changed_exact == baseline_exact


@pytest.mark.parametrize(
    "malformation",
    (
        "decision-duplicate-iteration",
        "decision-offset-iterations",
        "simplify-duplicate-iteration",
        "simplify-offset-iterations",
        "decision-interferer-count",
        "decision-node-count",
        "coalesce-conflicting-alias",
        "coalesce-cycle",
        "coalesce-forced-old-root",
        "coalesce-distinct-root-projection",
    ),
)
def test_structural_namespace_witness_rejects_invalid_allocator_sections(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    compile = _namespace_compile()
    descriptors = _namespace_descriptors(compile)
    decision = compile.fev.colorgraph_sections[-1]
    simplify = compile.fev.simplify_sections[-1]
    coalesce = compile.fev.coalesce_sections[-1]
    if malformation == "decision-duplicate-iteration":
        decision.decisions[1].iter_idx = decision.decisions[0].iter_idx
    elif malformation == "decision-offset-iterations":
        for row in decision.decisions:
            row.iter_idx += 1
    elif malformation == "simplify-duplicate-iteration":
        simplify.entries[1].iter_idx = simplify.entries[0].iter_idx
    elif malformation == "simplify-offset-iterations":
        for row in simplify.entries:
            row.iter_idx += 1
    elif malformation == "decision-interferer-count":
        decision.decisions[0].n_interferers += 1
    elif malformation == "decision-node-count":
        decision.n_nodes = len(decision.decisions) - 1
    elif malformation == "coalesce-conflicting-alias":
        coalesce.mappings.extend(((0, 1), (0, 2)))
    elif malformation == "coalesce-cycle":
        coalesce.mappings.extend(((0, 1), (1, 0)))
    elif malformation == "coalesce-forced-old-root":
        coalesce.forced_overrides.append((0, 1, 2))
        coalesce.forced_count = len(coalesce.forced_overrides)
    else:
        coalesce.distinct_roots -= 1
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_descriptors",
        lambda *_args: descriptors,
    )

    assert objectives_module._structural_namespace_witness(compile, 0) is None


def _v2_color_case(
    tmp_path: Path,
) -> tuple[
    RawCandidateEvidence,
    ObjectiveManifest,
    ParentEvidenceBundle,
    dict[str, Compile],
]:
    pcdump_text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    raws: dict[str, RawCandidateEvidence] = {}
    compiles: dict[str, Compile] = {}
    for side, source_text in (
        ("left", "int left(void) { return 1; }\n"),
        ("right", "int right(void) { return 2; }\n"),
        ("candidate", "int candidate(void) { return 3; }\n"),
    ):
        source = tmp_path / f"{side}.c"
        pcdump = tmp_path / f"{side}.pcdump"
        source.write_text(source_text, encoding="utf-8")
        emitted_pcdump = pcdump_text if side != "candidate" else f"{pcdump_text}\n"
        pcdump.write_text(emitted_pcdump, encoding="utf-8")
        candidate_id = "mask-000" if side == "candidate" else side
        raws[side] = RawCandidateEvidence(
            candidate_id=candidate_id,
            mask=0,
            source_path=str(source),
            source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
            compile_status="compiled",
            viable=True,
            pcdump_path=str(pcdump),
            checkdiff_evidence={},
            inspect_text=None,
            compiler_stderr="",
            pcdump_hash=hashlib.sha256(pcdump.read_bytes()).hexdigest(),
        )
        compiles[candidate_id] = _with_complete_virtual_identity(Compile.from_text(emitted_pcdump, FUNCTION, source_text))
    descriptors = _namespace_descriptors(compiles["left"])
    desired = {ig_idx: 0 for ig_idx in descriptors}
    target = build_target_spec(
        compiles["left"],
        desired,
        0,
        "force_proof_proxy",
        {},
    )
    bindings = {
        side: {
            "source_sha256": raws[side].source_hash,
            "pcdump_sha256": raws[side].pcdump_hash,
            "canonical_to_parent": {str(ig_idx): ig_idx for ig_idx in sorted(desired)},
        }
        for side in ("left", "right")
    }
    provenance = {
        "schema_version": COLOR_TARGET_SCHEMA_V2,
        "baseline_side": "left",
        "baseline_dump": raws["left"].pcdump_path,
        "baseline_dump_sha256": raws["left"].pcdump_hash,
        "parent_role_bindings": bindings,
        "namespace_schema": ROLE_NAMESPACE_SCHEMA,
    }
    objective = ObjectiveManifest(
        schema_version=OBJECTIVE_MANIFEST_SCHEMA,
        function=FUNCTION,
        class_id=0,
        target_spec={**asdict(target), "provenance": provenance},
        desired_phys=desired,
        color_donor="left",
        objobject_donor="left",
        stack_home_donor=None,
        references=_objective_stub().references,
    )
    parents = ParentEvidenceBundle(
        raws["left"],
        raws["right"],
        "cflags",
        "compiler",
        "object",
        "inspector-v1",
        "parsers",
    )
    return raws["candidate"], objective, parents, compiles


def _capture_color_role_maps(
    monkeypatch: pytest.MonkeyPatch,
    desired: dict[int, int],
) -> list[dict[int, int]]:
    captured: list[dict[int, int]] = []

    def profile(_text, _function, _class_id, role_map, **_kwargs):
        captured.append(dict(role_map))
        roles = tuple(sorted(desired))
        return ColorGraphProfile(
            assignments=tuple((role, desired[role]) for role in roles),
            simplify_order=roles,
            select_order=roles,
            interference_edges=frozenset(),
            coalesce_pairs=frozenset(),
            spills=frozenset(),
            complete=True,
        )

    monkeypatch.setattr(evaluator_module, "build_colorgraph_profile", profile)
    return captured


def _expected_complete_identity_role_map(
    compile: Compile,
    desired: Mapping[int, int],
) -> dict[int, int]:
    witness = objectives_module._structural_namespace_witness(compile, 0)
    assert witness is not None
    return {ig_idx: ig_idx if ig_idx in desired else 1_000_000 + ig_idx for ig_idx in range(witness["virtual_count"])}


@pytest.mark.parametrize("candidate_id", ("mask-000", "mask-1000"))
def test_candidate_color_profile_consumes_resolved_canonical_maps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: str,
) -> None:
    candidate, objective, parents, compiles = _v2_color_case(tmp_path)
    original_candidate_id = candidate.candidate_id
    candidate = replace(candidate, candidate_id=candidate_id, mask=int(candidate_id.removeprefix("mask-"), 2))
    compiles[candidate_id] = compiles[original_candidate_id]
    virtual_count = compiles["left"].fev.coalesce_sections[-1].n_virtuals
    domain = tuple(range(virtual_count))
    candidate_map = {role: role for role in domain}
    first, second = 47, 54
    candidate_map[first], candidate_map[second] = second, first
    donor_map = {role: role for role in domain}
    captured = _capture_color_role_maps(monkeypatch, dict(objective.desired_phys))
    monkeypatch.setattr(evaluator_module, "_compile", lambda raw, _function: compiles[raw.candidate_id])
    resolutions = {
        f"candidate:{candidate_id}": NamespaceMapResolution(
            artifact_id=f"candidate:{candidate_id}",
            source_sha256=candidate.source_hash,
            pcdump_sha256=candidate.pcdump_hash,
            raw_to_canonical=candidate_map,
            source="reviewed-v1",
        ),
        "parent:left": NamespaceMapResolution(
            artifact_id="parent:left",
            source_sha256=parents.left.source_hash,
            pcdump_sha256=parents.left.pcdump_hash,
            raw_to_canonical=donor_map,
            source="automatic-v5",
        ),
    }

    evaluator_module._color_axis(
        candidate,
        objective,
        parents,
        namespace_resolutions=resolutions,
    )

    assert captured == [candidate_map, donor_map]


def test_candidate_exact_parent_hashes_consume_reviewed_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, objective, parents, compiles = _v2_color_case(tmp_path)
    candidate = replace(
        candidate,
        source_path=parents.left.source_path,
        source_hash=parents.left.source_hash,
        pcdump_path=parents.left.pcdump_path,
        pcdump_hash=parents.left.pcdump_hash,
    )
    captured = _capture_color_role_maps(monkeypatch, dict(objective.desired_phys))
    monkeypatch.setattr(evaluator_module, "_compile", lambda raw, _function: compiles[raw.candidate_id])
    monkeypatch.setattr(
        evaluator_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: pytest.fail("reviewed hash binding did not bypass reanchor"),
    )

    evaluator_module._color_axis(candidate, objective, parents)

    expected = _expected_complete_identity_role_map(compiles["left"], objective.desired_phys)
    assert captured == [expected, expected]


def test_hybrid_equal_witness_inherits_parent_binding_despite_ambiguous_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, objective, parents, compiles = _v2_color_case(tmp_path)
    captured = _capture_color_role_maps(monkeypatch, dict(objective.desired_phys))
    monkeypatch.setattr(evaluator_module, "_compile", lambda raw, _function: compiles[raw.candidate_id])
    duplicate = {
        ig_idx: replace(
            descriptor,
            first_def_sig="same",
            use_site_multiset=(),
            var_name=None,
            var_confidence=None,
        )
        for ig_idx, descriptor in _namespace_descriptors(compiles["left"]).items()
    }
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_descriptors",
        lambda *_args: duplicate,
    )
    monkeypatch.setattr(
        evaluator_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: pytest.fail("equal witness did not bypass ambiguous reanchor"),
    )

    evaluator_module._color_axis(candidate, objective, parents)

    expected = _expected_complete_identity_role_map(compiles["left"], objective.desired_phys)
    assert captured == [expected, expected]


def test_matching_both_parent_witnesses_requires_agreeing_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, objective, parents, compiles = _v2_color_case(tmp_path)
    provenance = deepcopy(objective.target_spec["provenance"])
    keys = sorted(objective.desired_phys)
    provenance["parent_role_bindings"]["right"]["canonical_to_parent"] = {
        str(canonical): parent for canonical, parent in zip(keys, reversed(keys), strict=True)
    }
    objective = replace(
        objective,
        target_spec={**dict(objective.target_spec), "provenance": provenance},
    )
    monkeypatch.setattr(evaluator_module, "_compile", lambda raw, _function: compiles[raw.candidate_id])

    with pytest.raises(ValueError, match="conflicting proven parent role bindings"):
        evaluator_module._color_axis(candidate, objective, parents)


@pytest.mark.parametrize("same_dump", (False, True))
def test_changed_namespace_or_source_falls_back_to_semantic_reanchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    same_dump: bool,
) -> None:
    candidate, objective, parents, compiles = _v2_color_case(tmp_path)
    if same_dump:
        candidate = replace(
            candidate,
            pcdump_path=parents.left.pcdump_path,
            pcdump_hash=parents.left.pcdump_hash,
        )
    monkeypatch.setattr(evaluator_module, "_compile", lambda raw, _function: compiles[raw.candidate_id])
    monkeypatch.setattr(
        evaluator_module.role_descriptor,
        "prove_virtual_namespace_map",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        evaluator_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("semantic-fallback")),
    )

    with pytest.raises(ValueError, match="^semantic-fallback$"):
        evaluator_module._color_axis(candidate, objective, parents)


def test_ambiguous_binding_fallback_makes_viable_candidate_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, objective, parents, _compiles = _v2_color_case(tmp_path)
    candidate = replace(
        candidate,
        checkdiff_evidence={
            "match": False,
            "target_asm": ["+000: 38 60 00 00 li r3,0"],
            "current_asm": ["+000: 38 80 00 00 li r4,0"],
        },
        inspection_mode="no-objobjects",
    )
    monkeypatch.setattr(
        evaluator_module,
        "_color_axis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("ambiguous binding fallback")),
    )
    monkeypatch.setattr(evaluator_module, "_stack_axis", lambda *_args, **_kwargs: (0, 0, 0, 0))

    profile = profile_candidate(candidate, objective, parents=parents)

    assert profile.viable is True
    assert profile.complete is False
    assert profile.axes is None
    assert "incomplete-color-evidence" in profile.blockers


def test_derived_target_uses_correlated_exact_allocator_namespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump_text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    pcdump = tmp_path / "same.pcdump"
    pcdump.write_text(pcdump_text, encoding="utf-8")
    source = tmp_path / "same.c"
    source.write_text("", encoding="utf-8")
    compile = _with_complete_virtual_identity(Compile.from_text(pcdump_text, FUNCTION, ""))
    desired_roles = list(build_descriptors(compile, 0))[:2]
    desired = {desired_roles[0]: 22, desired_roles[1]: 21}
    target = build_target_spec(
        compile,
        desired,
        0,
        "force_proof_proxy",
        {"inference": "parent-register-diff", "parent": "left"},
    )
    objective = ObjectiveManifest(
        schema_version="delta-minimize-objectives.v1",
        function=FUNCTION,
        class_id=0,
        target_spec=asdict(target),
        desired_phys=desired,
        color_donor="left",
        objobject_donor="left",
        stack_home_donor="left",
        references=_objective_stub().references,
    )
    donor = RawCandidateEvidence("left", 0, str(source), "left", "compiled", True, str(pcdump), {}, None, "")
    candidate = replace(donor, candidate_id="candidate", source_hash="candidate")
    parents = ParentEvidenceBundle(
        donor,
        replace(donor, candidate_id="right", source_hash="right"),
        "cflags",
        "compiler",
        "object",
        "inspector-v1",
        "parsers",
    )
    stable_roles = tuple(desired)
    descriptors = build_descriptors(compile, 0)
    unique_descriptors = {
        ig_idx: replace(descriptor, first_def_sig=f"ig:{ig_idx}:{descriptor.first_def_sig}")
        for ig_idx, descriptor in descriptors.items()
    }
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_descriptors",
        lambda *_args: unique_descriptors,
    )
    monkeypatch.setattr(evaluator_module, "_compile", lambda *_args: compile)
    monkeypatch.setattr(
        evaluator_module,
        "build_colorgraph_profile",
        lambda *_args, **_kwargs: ColorGraphProfile(
            assignments=tuple((role, 0) for role in stable_roles),
            simplify_order=stable_roles,
            select_order=stable_roles,
            interference_edges=frozenset(),
            coalesce_pairs=frozenset(),
            spills=frozenset(),
            complete=True,
        ),
    )
    monkeypatch.setattr(
        evaluator_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("correlated exact namespace must bypass descriptor reanchoring")
        ),
    )

    assert evaluator_module._color_axis(candidate, objective, parents) == (
        2,
        0,
        0,
        0,
        0,
        0,
    )


def test_derived_target_does_not_reuse_raw_namespace_when_role_semantics_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcdump_text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    donor_compile = Compile.from_text(pcdump_text, FUNCTION, "")
    candidate_compile = deepcopy(donor_compile)
    donor_descriptors = build_descriptors(donor_compile, 0)
    candidate_descriptors = deepcopy(donor_descriptors)
    changed_ig = next(iter(candidate_descriptors))
    candidate_descriptors[changed_ig] = replace(
        candidate_descriptors[changed_ig],
        first_def_sig=f"changed:{candidate_descriptors[changed_ig].first_def_sig}",
    )
    for block in candidate_compile.fn.passes[0].blocks:
        for instruction in block.instructions:
            if ("r", changed_ig) in instruction.regs:
                instruction.operands = f"{instruction.operands}+semantic-change"
    desired = {changed_ig: 22}
    target = build_target_spec(
        donor_compile,
        desired,
        0,
        "force_proof_proxy",
        {"inference": "parent-register-diff"},
    )
    objective = replace(
        _objective_stub(),
        target_spec=asdict(target),
        desired_phys=desired,
    )
    donor = _raw_stub()
    donor = replace(donor, candidate_id="left", source_hash="left")
    candidate = replace(donor, candidate_id="candidate", source_hash="candidate")
    parents = ParentEvidenceBundle(
        donor,
        replace(donor, candidate_id="right", source_hash="right"),
        "cflags",
        "compiler",
        "object",
        "inspector-v1",
        "parsers",
    )
    monkeypatch.setattr(
        evaluator_module,
        "_compile",
        lambda raw, _function: candidate_compile if raw.candidate_id == "candidate" else donor_compile,
    )
    original_build = objectives_module.role_descriptor.build_descriptors

    def descriptors(compile: Compile, class_id: int):
        if compile is candidate_compile:
            return candidate_descriptors
        if compile is donor_compile:
            return donor_descriptors
        return original_build(compile, class_id)

    monkeypatch.setattr(objectives_module.role_descriptor, "build_descriptors", descriptors)
    monkeypatch.setattr(
        evaluator_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("semantic-reanchor-required")),
    )

    with pytest.raises(ValueError, match="^semantic-reanchor-required$"):
        evaluator_module._color_axis(candidate, objective, parents)


def test_stack_inputs_build_real_frame_and_explicit_empty_bridge(monkeypatch, tmp_path: Path) -> None:
    pcdump = tmp_path / "candidate.pcdump"
    source = tmp_path / "candidate.c"
    pcdump.write_text("pcdump\n", encoding="utf-8")
    source.write_text("int f(void) { return 0; }\n", encoding="utf-8")
    evidence = RawCandidateEvidence(
        candidate_id="candidate",
        mask=0,
        source_path=str(source),
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        compile_status="compiled",
        viable=True,
        pcdump_path=str(pcdump),
        checkdiff_evidence={
            "target_asm": ["+000: 38 60 00 00 li r3,0", ""],
            "current_asm": ["+000: 38 60 00 00 li r3,0", ""],
            "classification": {
                "offset_discrepancies": [],
                "stack_frame_sizes": {
                    "current_frame_size": 16,
                    "expected_frame_size": 16,
                },
            },
        },
        inspect_text=None,
        compiler_stderr="",
    )
    frame = {
        "function": "f",
        "current": {
            "frame_size": 16,
            "stack_home_assignment_status": "resolved-symbolic-homes",
            "stack_home_assignments": [],
        },
    }
    monkeypatch.setattr(
        evaluator_module,
        "analyze_frame_reservations",
        lambda *args, **kwargs: frame,
    )

    actual_frame, bridge = evaluator_module._evidence_frame_and_stack(evidence, "f")

    assert actual_frame == frame
    assert bridge == {
        "status": "no-candidates",
        "function": "f",
        "frame_size": 16,
        "candidate_count": 0,
        "candidates": [],
    }


def test_capture_candidate_rebuilds_when_cached_pcdump_was_deleted(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    calls = {"score": 0, "inspect": 0}

    def score_rows(_rows, _config):
        calls["score"] += 1
        pcdump.write_text(f"pcdump-{calls['score']}", encoding="utf-8")
        return [_score_row(candidate, pcdump)]

    def inspect_source(*_args, **_kwargs):
        calls["inspect"] += 1
        return f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"

    store = _store(tmp_path)
    backends = EvaluationBackends(score_rows, inspect_source)
    capture_candidate(candidate, _config(tmp_path), backends=backends, store=store)
    pcdump.unlink()

    rebuilt = capture_candidate(candidate, _config(tmp_path), backends=backends, store=store)

    assert Path(rebuilt.pcdump_path or "").read_text(encoding="utf-8") == "pcdump-2"
    assert calls == {"score": 2, "inspect": 1}


def test_capture_candidate_rebuilds_cached_viable_evidence_without_checkdiff(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    calls = {"score": 0, "inspect": 0}

    def score_rows(_rows, _config):
        calls["score"] += 1
        row = _score_row(candidate, pcdump)
        if calls["score"] == 1:
            row["checkdiff_evidence"] = None
        return [row]

    def inspect_source(*_args, **_kwargs):
        calls["inspect"] += 1
        return f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"

    store = _store(tmp_path)
    backends = EvaluationBackends(score_rows, inspect_source)
    first = capture_candidate(candidate, _config(tmp_path), backends=backends, store=store)
    second = capture_candidate(candidate, _config(tmp_path), backends=backends, store=store)

    assert first.checkdiff_evidence is None
    assert second.checkdiff_evidence is not None
    assert calls == {"score": 2, "inspect": 1}


@pytest.mark.parametrize(
    ("stale_pcdump", "stale_diagnostics"),
    [
        pytest.param(
            True,
            f"function '{FUNCTION}' not in compiled pcdump",
            id="missing-target-function",
        ),
        pytest.param(
            True,
            "### mwcceppc.exe Compiler:\n#   Error: broken declaration\nCompilation finished.\n",
            id="inspector-compile-rejection",
        ),
        pytest.param(
            False,
            "candidate failed",
            id="non-mwcc-diagnostics",
        ),
    ],
)
def test_capture_candidate_rebuilds_untrusted_cached_nonviable_evidence(
    tmp_path: Path,
    stale_pcdump: bool,
    stale_diagnostics: str,
) -> None:
    candidate = _candidate(tmp_path)
    config = _config(tmp_path)
    store = _store(tmp_path)
    pcdump = tmp_path / "stale.pcdump"
    pcdump.write_text("Starting function other\n", encoding="utf-8")
    stale = RawCandidateEvidence(
        candidate_id=candidate.candidate_id,
        mask=candidate.mask,
        source_path=str(candidate.source_path),
        source_hash=candidate.source_hash,
        compile_status="rejected",
        viable=False,
        pcdump_path=str(pcdump) if stale_pcdump else None,
        checkdiff_evidence=None,
        inspect_text=None,
        compiler_stderr=stale_diagnostics,
        inspection_mode="objobjects",
        pcdump_hash=(hashlib.sha256(pcdump.read_bytes()).hexdigest() if stale_pcdump else None),
    )
    store.write_evidence(store.evidence_key(candidate, config), stale.to_dict())
    calls = {"score": 0}

    def compile_rejected(_rows, _config):
        calls["score"] += 1
        return [
            {
                "candidate_id": candidate.candidate_id,
                "error": "pcdump missing",
                "score_error_kind": "candidate",
                "score_returncode": 0,
                "score_stderr": "mwcceppc_debug.exe compiler error: syntax error",
            }
        ]

    rebuilt = capture_candidate(
        candidate,
        config,
        backends=EvaluationBackends(
            compile_rejected,
            lambda *_args, **_kwargs: pytest.fail(),
        ),
        store=store,
    )

    assert rebuilt.viable is False
    assert rebuilt.pcdump_path is None
    assert rebuilt.compiler_stderr == "mwcceppc_debug.exe compiler error: syntax error"
    assert calls == {"score": 1}


def test_capture_candidate_reuses_cached_concrete_compile_rejection(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    config = _config(tmp_path)
    store = _store(tmp_path)
    calls = {"score": 0}

    def compile_rejected(_rows, _config):
        calls["score"] += 1
        return [
            {
                "candidate_id": candidate.candidate_id,
                "error": "pcdump missing",
                "score_error_kind": "candidate",
                "score_returncode": 0,
                "score_stderr": "mwcceppc_debug.exe compiler error: syntax error",
            }
        ]

    backends = EvaluationBackends(
        compile_rejected,
        lambda *_args, **_kwargs: pytest.fail(),
    )
    first = capture_candidate(candidate, config, backends=backends, store=store)
    second = capture_candidate(candidate, config, backends=backends, store=store)

    assert second == first
    assert calls == {"score": 1}


def test_evidence_key_includes_inspector_invocation_mode(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    store = _store(tmp_path)

    with_objobjects = store.evidence_key(candidate, _config(tmp_path, include_objobjects=True))
    without_objobjects = store.evidence_key(candidate, _config(tmp_path, include_objobjects=False))

    assert with_objobjects.digest() != without_objobjects.digest()
    assert "mode=objobjects" in with_objobjects.inspector_version
    assert "mode=no-objobjects" in without_objobjects.inspector_version


def test_compile_rejection_is_nonviable_not_incomplete(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    row = {
        "candidate_id": candidate.candidate_id,
        "source_file": str(candidate.source_path),
        "error": "pcdump missing",
        "score_error_kind": "candidate",
        "score_returncode": 0,
        "score_stderr": "mwcceppc_debug.exe compiler error: syntax error",
    }
    evidence = capture_candidate(
        candidate,
        _config(tmp_path),
        backends=EvaluationBackends(lambda _rows, _config: [row], lambda *_args, **_kwargs: pytest.fail()),
        store=_store(tmp_path),
    )
    profile = profile_candidate(evidence, _objective_stub(), parents=None)

    assert evidence.compile_status == "rejected"
    assert evidence.viable is False
    assert profile.complete is True
    assert profile.axes is None


def test_compiled_candidate_missing_target_function_is_cached_nonviable(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("Starting function other\n", encoding="utf-8")
    calls = {"score": 0, "inspect": 0}

    def score_rows(_rows, _config):
        calls["score"] += 1
        return [
            {
                "candidate_id": candidate.candidate_id,
                "source_file": str(candidate.source_path),
                "pcdump_path": str(pcdump),
                "error": f"function '{FUNCTION}' not in compiled pcdump",
                "score_error_kind": "candidate",
                "score_returncode": 0,
                "terminal_safe": True,
            }
        ]

    def inspect_source(*_args, **_kwargs):
        calls["inspect"] += 1
        pytest.fail("a nonviable candidate must not be inspected")

    store = _store(tmp_path)
    config = _config(tmp_path)
    backends = EvaluationBackends(score_rows, inspect_source)
    first = capture_candidate(candidate, config, backends=backends, store=store)
    second = capture_candidate(candidate, config, backends=backends, store=store)
    profile = profile_candidate(first, _objective_stub(), parents=None)

    assert second == first
    assert first.compile_status == "rejected"
    assert first.viable is False
    assert first.pcdump_path == str(pcdump)
    assert first.pcdump_hash == hashlib.sha256(pcdump.read_bytes()).hexdigest()
    assert first.checkdiff_evidence is None
    assert first.inspect_text is None
    assert "candidate-target-function-missing" in first.blockers
    assert profile.compile_status == "rejected"
    assert profile.viable is False
    assert profile.complete is True
    assert profile.axes is None
    assert profile.blockers == first.blockers
    assert calls == {"score": 1, "inspect": 0}


@pytest.mark.parametrize(
    "mutation",
    (
        "not-terminal-safe",
        "wrong-function",
        "missing-pcdump",
        "infrastructure-kind",
        "missing-kind",
        "invalid-kind",
        "target-present",
    ),
)
def test_unproven_missing_target_candidate_remains_infrastructure(
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("Starting function other\n", encoding="utf-8")
    row = {
        "candidate_id": candidate.candidate_id,
        "source_file": str(candidate.source_path),
        "pcdump_path": str(pcdump),
        "error": f"function '{FUNCTION}' not in compiled pcdump",
        "score_error_kind": "candidate",
        "score_returncode": 0,
        "terminal_safe": True,
    }
    if mutation == "not-terminal-safe":
        row["terminal_safe"] = False
    elif mutation == "wrong-function":
        row["error"] = "function 'other' not in compiled pcdump"
    elif mutation == "missing-pcdump":
        row["pcdump_path"] = None
    elif mutation == "infrastructure-kind":
        row["score_error_kind"] = "infrastructure"
    elif mutation == "missing-kind":
        del row["score_error_kind"]
    elif mutation == "invalid-kind":
        row["score_error_kind"] = "bogus"
    else:
        pcdump.write_text(f"Starting function {FUNCTION}\n", encoding="utf-8")

    store = _store(tmp_path)
    key = store.evidence_key(candidate, _config(tmp_path))
    with pytest.raises(DeltaMinimizeError, match="^candidate-score-infrastructure$"):
        capture_candidate(
            candidate,
            _config(tmp_path),
            backends=EvaluationBackends(
                lambda _rows, _config: [row],
                lambda *_args, **_kwargs: pytest.fail(),
            ),
            store=store,
        )
    assert store.load_evidence(key) is None


def test_cached_missing_target_evidence_revalidates_its_pcdump(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    calls = 0

    def score_rows(_rows, _config):
        nonlocal calls
        calls += 1
        pcdump.write_text(f"Starting function other generation {calls}\n", encoding="utf-8")
        return [
            {
                "candidate_id": candidate.candidate_id,
                "source_file": str(candidate.source_path),
                "pcdump_path": str(pcdump),
                "error": f"function '{FUNCTION}' not in compiled pcdump",
                "score_error_kind": "candidate",
                "score_returncode": 0,
                "terminal_safe": True,
            }
        ]

    store = _store(tmp_path)
    config = _config(tmp_path)
    backends = EvaluationBackends(score_rows, lambda *_args, **_kwargs: pytest.fail())
    first = capture_candidate(candidate, config, backends=backends, store=store)
    pcdump.write_text("tampered\n", encoding="utf-8")
    second = capture_candidate(candidate, config, backends=backends, store=store)

    assert calls == 2
    assert second.pcdump_hash != first.pcdump_hash
    assert second.pcdump_hash == hashlib.sha256(pcdump.read_bytes()).hexdigest()


def test_cached_missing_target_evidence_revalidates_semantic_absence(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    config = _config(tmp_path)
    store = _store(tmp_path)
    forged_pcdump = tmp_path / "forged.pcdump"
    forged_pcdump.write_text(f"Starting function {FUNCTION}\n", encoding="utf-8")
    forged = RawCandidateEvidence(
        candidate_id=candidate.candidate_id,
        mask=candidate.mask,
        source_path=str(candidate.source_path),
        source_hash=candidate.source_hash,
        compile_status="rejected",
        viable=False,
        pcdump_path=str(forged_pcdump),
        checkdiff_evidence=None,
        inspect_text=None,
        compiler_stderr="",
        blockers=("candidate-target-function-missing",),
        inspection_mode="objobjects",
        pcdump_hash=hashlib.sha256(forged_pcdump.read_bytes()).hexdigest(),
    )
    key = store.evidence_key(candidate, config)
    store.write_evidence(key, forged.to_dict())
    fresh_pcdump = tmp_path / "fresh.pcdump"
    calls = 0

    def score_rows(_rows, _config):
        nonlocal calls
        calls += 1
        fresh_pcdump.write_text("Starting function other\n", encoding="utf-8")
        return [
            {
                "candidate_id": candidate.candidate_id,
                "source_file": str(candidate.source_path),
                "pcdump_path": str(fresh_pcdump),
                "error": f"function '{FUNCTION}' not in compiled pcdump",
                "score_error_kind": "candidate",
                "score_returncode": 0,
                "terminal_safe": True,
            }
        ]

    rebuilt = capture_candidate(
        candidate,
        config,
        backends=EvaluationBackends(score_rows, lambda *_args, **_kwargs: pytest.fail()),
        store=store,
    )

    assert calls == 1
    assert rebuilt.pcdump_path == str(fresh_pcdump)
    assert rebuilt.pcdump_hash == hashlib.sha256(fresh_pcdump.read_bytes()).hexdigest()
    assert store.load_evidence(key) == rebuilt.to_dict()


@pytest.mark.parametrize("stderr", ["", "candidate failed"])
def test_candidate_failure_without_compile_diagnostics_fails_closed(
    tmp_path: Path,
    stderr: str,
) -> None:
    candidate = _candidate(tmp_path)
    row = {
        "candidate_id": candidate.candidate_id,
        "error": "pcdump missing",
        "score_error_kind": "candidate",
        "score_returncode": 0,
        "score_stderr": stderr,
    }

    with pytest.raises(DeltaMinimizeError, match="candidate-score-infrastructure"):
        capture_candidate(
            candidate,
            _config(tmp_path),
            backends=EvaluationBackends(lambda _rows, _config: [row], lambda *_args: pytest.fail()),
            store=_store(tmp_path),
        )


@pytest.mark.parametrize("missing", ["pcdump_path", "checkdiff_evidence", "inspect_text"])
def test_viable_missing_required_evidence_is_incomplete(missing: str) -> None:
    evidence = _raw_stub()
    profile = profile_candidate(replace(evidence, **{missing: None}), _objective_stub(), parents=None)

    assert profile.viable is True
    assert profile.complete is False
    assert f"missing-{missing.replace('_', '-')}" in profile.blockers


def test_no_objobjects_is_explicitly_provisional_but_complete_for_requested_axes() -> None:
    evidence = replace(_raw_stub(), inspection_mode="no-objobjects", inspect_text=None)
    profile = profile_candidate(evidence, _objective_stub(), parents=None)

    assert "missing-inspect-text" not in profile.blockers
    assert "objobjects-disabled-provisional" in profile.blockers


def test_exact_object_match_requires_literal_true() -> None:
    for raw_match, expected in ((True, True), (1, False), ("true", False), (False, False)):
        evidence = replace(
            _raw_stub(),
            checkdiff_evidence={**dict(_raw_stub().checkdiff_evidence or {}), "match": raw_match},
        )
        profile = profile_candidate(evidence, _objective_stub(), parents=None)
        assert profile.exact_object_match is expected


def test_inspector_timeout_is_run_level_incomplete_and_not_cached(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    store = _store(tmp_path)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("inspect", 7)

    with pytest.raises(DeltaMinimizeError, match="inspector-timeout") as exc_info:
        capture_candidate(
            candidate,
            _config(tmp_path),
            backends=EvaluationBackends(lambda _rows, _config: [_score_row(candidate, pcdump)], timeout),
            store=store,
        )
    assert exc_info.value.reason == "inspector-timeout"
    assert store.load_evidence(store.evidence_key(candidate, _config(tmp_path))) is None


def test_inspector_timeout_never_recovers_complete_final_output(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    store = _store(tmp_path)

    def timeout_after_write(_source, _function, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
            "ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: late\n"
            f"  Type: int\n  Scope: {FUNCTION}\n  Expression: late\n"
            "Compilation finished.\n",
            encoding="utf-8",
        )
        raise subprocess.TimeoutExpired("inspect", 7)

    config = _config(tmp_path)
    with pytest.raises(DeltaMinimizeError, match="^inspector-timeout$"):
        capture_candidate(
            candidate,
            config,
            backends=EvaluationBackends(
                lambda _rows, _config: [_score_row(candidate, pcdump)],
                timeout_after_write,
            ),
            store=store,
        )

    assert store.load_evidence(store.evidence_key(candidate, config)) is None


@pytest.mark.parametrize(
    "staging_text",
    [
        "FUNCTION: partial\n",
        (
            f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
            "ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: unpromoted\n"
            f"  Type: int\n  Scope: {FUNCTION}\n  Expression: unpromoted\n"
            "Compilation finished.\n"
        ),
    ],
    ids=["partial", "complete-looking"],
)
def test_inspector_failure_never_recovers_unpromoted_staging_output(
    tmp_path: Path,
    staging_text: str,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    store = _store(tmp_path)

    def failed_with_staging(_source, _function, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.with_name(f"{output.name}.stage.invocation-a").write_text(
            staging_text,
            encoding="utf-8",
        )
        raise DeltaMinimizeError("inspector-failed")

    config = _config(tmp_path)
    with pytest.raises(DeltaMinimizeError, match="^inspector-failed$"):
        capture_candidate(
            candidate,
            config,
            backends=EvaluationBackends(
                lambda _rows, _config: [_score_row(candidate, pcdump)],
                failed_with_staging,
            ),
            store=store,
        )

    assert store.load_evidence(store.evidence_key(candidate, config)) is None


def test_inspector_compile_error_is_run_level_and_retried(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    store = _store(tmp_path)
    calls = {"inspect": 0}

    def rejected_inspection(_source, _function, output, **_kwargs):
        calls["inspect"] += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "### mwcceppc.exe Compiler:\n#    10: broken declaration\n#   Error: ^^^\nCompilation finished.\n",
            encoding="utf-8",
        )
        raise DeltaMinimizeError("inspector-failed")

    backends = EvaluationBackends(
        lambda _rows, _config: [_score_row(candidate, pcdump)],
        rejected_inspection,
    )
    config = _config(tmp_path)
    for _attempt in range(2):
        with pytest.raises(DeltaMinimizeError, match="^inspector-failed$"):
            capture_candidate(
                candidate,
                config,
                backends=backends,
                store=store,
            )
        assert store.load_evidence(store.evidence_key(candidate, config)) is None

    assert calls == {"inspect": 2}


def test_complete_inspector_artifact_is_recovered_after_wrapper_failure(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    store = _store(tmp_path)

    def completed_inspection(_source, _function, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
            "ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: value\n"
            f"  Type: int\n  Scope: {FUNCTION}\n  Expression: value\n"
            "FUNCTION: other\nFrontend: OBJOBJECTS\n"
            "Compilation finished.\n",
            encoding="utf-8",
        )
        raise DeltaMinimizeError("inspector-failed")

    evidence = capture_candidate(
        candidate,
        _config(tmp_path),
        backends=EvaluationBackends(
            lambda _rows, _config: [_score_row(candidate, pcdump)],
            completed_inspection,
        ),
        store=store,
    )

    assert evidence.viable is True
    assert evidence.inspect_text is not None
    assert "Compilation finished." in evidence.inspect_text


def test_inspector_failure_does_not_recover_preexisting_stable_output(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("pcdump", encoding="utf-8")
    store = _store(tmp_path)
    inspect_output = store.inspect_output_path(candidate.candidate_id)
    inspect_output.parent.mkdir(parents=True, exist_ok=True)
    inspect_output.write_text(
        f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
        "ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: stale\n"
        f"  Type: int\n  Scope: {FUNCTION}\n  Expression: stale\n"
        "Compilation finished.\n",
        encoding="utf-8",
    )
    invocation = {"saw_preexisting_output": None}

    def failed_inspection(_source, _function, output, **_kwargs):
        invocation["saw_preexisting_output"] = output.exists()
        raise DeltaMinimizeError("inspector-failed")

    config = _config(tmp_path)
    with pytest.raises(DeltaMinimizeError, match="^inspector-failed$"):
        capture_candidate(
            candidate,
            config,
            backends=EvaluationBackends(
                lambda _rows, _config: [_score_row(candidate, pcdump)],
                failed_inspection,
            ),
            store=store,
        )

    assert invocation == {"saw_preexisting_output": False}
    assert store.load_evidence(store.evidence_key(candidate, config)) is None


def test_raw_evidence_roundtrip_rejects_malformed_data() -> None:
    raw = _raw_stub()
    assert RawCandidateEvidence.from_dict(raw.to_dict()) == raw
    with pytest.raises(DeltaMinimizeError, match="invalid-raw-candidate-evidence"):
        RawCandidateEvidence.from_dict({**raw.to_dict(), "mask": True})
    with pytest.raises(DeltaMinimizeError, match="invalid-raw-candidate-evidence"):
        RawCandidateEvidence.from_dict({**raw.to_dict(), "surprise": 1})


def test_profile_candidate_builds_all_four_metric_vectors_from_real_parsers(
    tmp_path: Path,
) -> None:
    pcdump_text = f"""\
Starting function {FUNCTION}
[COALESCE] enter class=0 n_virtuals=80
[COALESCE] natural mappings (virt -> root):
  (none - no virtuals coalesced)
[COALESCE] exit class=0 n_virtuals=80 distinct_roots=80 forced=0

SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=80)
iter ig_idx degree arraySize flags notes
0 58 0 0 0x00

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
iter ig_idx reg degree nIntfr flags
0 58 r22 0 0 0x00
"""
    donor_pcdump = tmp_path / "donor.pcdump"
    candidate_pcdump = tmp_path / "candidate.pcdump"
    donor_pcdump.write_text(pcdump_text, encoding="utf-8")
    candidate_pcdump.write_text(pcdump_text, encoding="utf-8")
    donor_source = tmp_path / "donor.c"
    candidate_source = tmp_path / "candidate.c"
    donor_source.write_text("", encoding="utf-8")
    candidate_source.write_text("", encoding="utf-8")

    objective = ObjectiveManifest(
        schema_version="delta-minimize-objectives.v1",
        function=FUNCTION,
        class_id=0,
        target_spec={},
        desired_phys={0: 22},
        color_donor="left",
        objobject_donor="left",
        stack_home_donor="left",
        references=_objective_stub().references,
    )

    def inspect_text(first: str, second: str) -> str:
        return (
            f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
            f"ObjObject @ 0x10\n  Kind: DLOCAL\n  Name: {first}\n"
            f"  Type: int\n  Scope: {FUNCTION}\n  Expression: {first}\n"
            f"ObjObject @ 0x20\n  Kind: DLOCAL\n  Name: {second}\n"
            f"  Type: int\n  Scope: {FUNCTION}\n  Expression: {second}\n"
        )

    def stack_checkdiff(offset: int, *, current_opcode: str) -> dict[str, object]:
        assignment = {
            "assignment_order": 0,
            "symbol": "home",
            "offset": offset,
            "expected_offset": 8,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stw"],
            "first_access": {
                "opcode": "stw",
                "operands": "r3,home(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 1,
            },
        }
        return {
            "function": FUNCTION,
            "match": False,
            "target_asm": ["+000: 38 60 00 00 li r3,0"],
            "current_asm": [f"+000: 7C 60 00 00 {current_opcode} r3,r0"],
            "classification": {"primary": "instruction-sequence"},
            "color_role_map": {58: 0},
            "frame_report": {
                "function": FUNCTION,
                "current": {
                    "frame_size": 32,
                    "stack_home_assignment_status": "resolved-symbolic-homes",
                    "stack_home_assignments": [assignment],
                },
                "expected": {"frame_size": 32},
            },
            "stack_slot_report": {
                "status": "no-candidates",
                "function": FUNCTION,
                "candidate_count": 0,
                "candidates": [],
            },
        }

    donor = RawCandidateEvidence(
        "left",
        0,
        str(donor_source),
        "donor-hash",
        "compiled",
        True,
        str(donor_pcdump),
        stack_checkdiff(8, current_opcode="li"),
        inspect_text("alpha", "beta"),
        "",
    )
    candidate = RawCandidateEvidence(
        "candidate",
        1,
        str(candidate_source),
        "candidate-hash",
        "compiled",
        True,
        str(candidate_pcdump),
        stack_checkdiff(12, current_opcode="mr"),
        inspect_text("beta", "alpha"),
        "",
    )
    parents = ParentEvidenceBundle(
        donor,
        replace(donor, candidate_id="right", source_hash="right-hash"),
        "cflags",
        "compiler",
        "object",
        "inspector-v1;mode=objobjects",
        "parsers",
    )
    assert ParentEvidenceBundle.from_dict(json.loads(json.dumps(parents.to_dict()))) == parents

    profile = profile_candidate(candidate, objective, parents=parents)

    assert profile.complete is True
    assert profile.axes is not None
    assert profile.axes.opcode == (1, 0)
    assert profile.axes.color == (0, 0, 0, 0, 0, 0)
    assert profile.axes.objobjects == (0, 1)
    assert profile.axes.stack_homes == (1, 4, 0, 0)


def test_stack_axis_scores_absolute_expected_truth_not_wholesale_donor(tmp_path: Path) -> None:
    pcdump = tmp_path / "same.pcdump"
    pcdump.write_text(
        f"Starting function {FUNCTION}\n"
        "[COALESCE] enter class=0 n_virtuals=1\n"
        "[COALESCE] natural mappings (virt -> root):\n"
        "  (none - no virtuals coalesced)\n"
        "[COALESCE] exit class=0 n_virtuals=1 distinct_roots=1 forced=0\n\n"
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=1)\n"
        "iter ig_idx degree arraySize flags notes\n0 0 0 0 0x00\n\n"
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)\n"
        "iter ig_idx reg degree nIntfr flags\n0 0 r3 0 0 0x00\n",
        encoding="utf-8",
    )
    source = tmp_path / "candidate.c"
    source.write_text("", encoding="utf-8")

    def checkdiff(current_offset: int, expected_offset: int, current_frame: int) -> dict[str, object]:
        assignment = {
            "assignment_order": 0,
            "symbol": "home",
            "offset": current_offset,
            "expected_offset": expected_offset,
            "size": 4,
            "kind": "local-or-temporary",
            "access_count": 1,
            "opcodes": ["stw"],
            "first_access": {
                "opcode": "stw",
                "operands": "r3,home(r1)",
                "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                "block_idx": 0,
                "instr_idx": 1,
            },
        }
        return {
            "function": FUNCTION,
            "match": False,
            "target_asm": ["+000: 38 60 00 00 li r3,0"],
            "current_asm": ["+000: 38 60 00 00 li r3,0"],
            "classification": {"primary": "instruction-identical"},
            "color_role_map": {0: 0},
            "frame_report": {
                "function": FUNCTION,
                "current": {
                    "frame_size": current_frame,
                    "stack_home_assignment_status": "resolved-symbolic-homes",
                    "stack_home_assignments": [assignment],
                },
                "expected": {"frame_size": 32},
            },
            "stack_slot_report": {
                "status": "no-candidates",
                "function": FUNCTION,
                "candidate_count": 0,
                "candidates": [],
            },
        }

    inspect_text = f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n"
    donor = RawCandidateEvidence(
        "left",
        0,
        str(source),
        "left",
        "compiled",
        True,
        str(pcdump),
        checkdiff(8, 12, 40),
        inspect_text,
        "",
    )
    candidate = RawCandidateEvidence(
        "candidate",
        1,
        str(source),
        "candidate",
        "compiled",
        True,
        str(pcdump),
        checkdiff(12, 12, 32),
        inspect_text,
        "",
    )
    parents = ParentEvidenceBundle(
        donor,
        replace(donor, candidate_id="right", source_hash="right"),
        "cflags",
        "compiler",
        "object",
        "inspector-v1",
        "parsers",
    )
    objective = ObjectiveManifest(
        schema_version="delta-minimize-objectives.v1",
        function=FUNCTION,
        class_id=0,
        target_spec={},
        desired_phys={0: 3},
        color_donor="left",
        objobject_donor="left",
        stack_home_donor="left",
        references={
            **dict(_objective_stub().references),
            "stack-homes": AxisReference(
                "absolute",
                "checkdiff",
                "left",
                "lower absolute distance",
                False,
                (),
            ),
        },
    )

    profile = profile_candidate(candidate, objective, parents=parents)

    assert profile.complete is True
    assert profile.axes is not None
    assert profile.axes.stack_homes == (0, 0, 0, 0)


def test_stack_proxy_donor_reconstructs_retained_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "candidate.c"
    source.write_text("", encoding="utf-8")
    pcdump = tmp_path / "candidate.pcdump"
    pcdump.write_text("retained pcdump", encoding="utf-8")

    def frame(offset: int) -> dict[str, object]:
        return {
            "function": FUNCTION,
            "current": {
                "frame_size": 32,
                "stack_home_assignment_status": "resolved-symbolic-homes",
                "stack_home_assignments": [
                    {
                        "assignment_order": 0,
                        "symbol": "home",
                        "offset": offset,
                        "size": 4,
                        "kind": "local-or-temporary",
                        "access_count": 1,
                        "opcodes": ["stw"],
                        "first_access": {
                            "opcode": "stw",
                            "operands": "r3,home(r1)",
                            "pass": "FINAL CODE AFTER INSTRUCTION SCHEDULING",
                            "block_idx": 0,
                            "instr_idx": 1,
                        },
                    }
                ],
            },
            "expected": {"frame_size": 32},
        }

    base_checkdiff = {
        "function": FUNCTION,
        "match": False,
        "target_asm": ["+000: 38 60 00 00 li r3,0"],
        "current_asm": ["+000: 38 60 00 00 li r3,0"],
        "classification": {"primary": "instruction-identical"},
    }
    candidate = RawCandidateEvidence(
        "candidate",
        1,
        str(source),
        "candidate",
        "compiled",
        True,
        str(pcdump),
        {**base_checkdiff, "frame_report": frame(12)},
        f"FUNCTION: {FUNCTION}\nFrontend: OBJOBJECTS\n",
        "",
    )
    donor = replace(candidate, candidate_id="left", source_hash="left", checkdiff_evidence=base_checkdiff)
    parents = ParentEvidenceBundle(
        donor,
        replace(donor, candidate_id="right", source_hash="right"),
        "cflags",
        "compiler",
        "object",
        "inspector-v1",
        "parsers",
    )
    objective = replace(
        _objective_stub(),
        stack_home_donor="left",
        references={
            **dict(_objective_stub().references),
            "stack-homes": AxisReference(
                "proxy",
                "retained parent evidence",
                "left",
                "unresolved symbolic home",
                True,
                ("symbol:home",),
            ),
        },
    )
    calls: list[str] = []

    stack_report = {
        "status": "no-candidates",
        "function": FUNCTION,
        "candidate_count": 0,
        "candidates": [],
    }

    def reconstruct(evidence: RawCandidateEvidence, function: str):
        calls.append(evidence.candidate_id)
        if evidence.candidate_id == "left":
            return frame(8), stack_report
        assert evidence.candidate_id == "candidate"
        return frame(12), stack_report

    monkeypatch.setattr(evaluator_module, "_evidence_frame_and_stack", reconstruct)
    monkeypatch.setattr(
        evaluator_module,
        "_frame_and_stack",
        lambda *_args, **_kwargs: pytest.fail("legacy payload-only stack extraction used"),
    )

    assert evaluator_module._stack_axis(candidate, objective, parents) == (1, 0, 0, 0)
    assert calls == ["candidate", "left"]


def _raw_stub() -> RawCandidateEvidence:
    return RawCandidateEvidence(
        candidate_id="candidate",
        mask=0,
        source_path="/candidate.c",
        source_hash="source-hash",
        compile_status="compiled",
        viable=True,
        pcdump_path="/candidate.pcdump",
        checkdiff_evidence={
            "function": FUNCTION,
            "match": False,
            "target_asm": ["+000: 38 60 00 00 li r3,0"],
            "current_asm": ["+000: 38 80 00 00 li r4,0"],
            "classification": {"primary": "register-allocation"},
        },
        inspect_text="FUNCTION: mnVibration_80248644\nFrontend: OBJOBJECTS\n",
        compiler_stderr="",
        inspection_mode="objobjects",
    )


def _objective_stub() -> ObjectiveManifest:
    references = {
        axis: AxisReference(kind, artifact, donor, reason, False)
        for axis, kind, artifact, donor, reason in (
            ("opcode", "absolute", "expected", None, "expected"),
            ("color", "mixed", "color", "left", "color"),
            ("objobjects", "proxy", "inspect", "left", "obj"),
            ("stack-homes", "absolute", "stack", None, "stack"),
        )
    }
    return ObjectiveManifest(
        schema_version="delta-minimize-objectives.v1",
        function=FUNCTION,
        class_id=0,
        target_spec={},
        desired_phys={},
        color_donor="left",
        objobject_donor="left",
        stack_home_donor=None,
        references=references,
    )
