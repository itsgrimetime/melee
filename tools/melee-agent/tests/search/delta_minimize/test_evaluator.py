from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

import src.search.delta_minimize.evaluator as evaluator_module
import src.search.delta_minimize.objectives as objectives_module
from src.mwcc_debug.colorgraph_profile import ColorGraphProfile
from src.mwcc_debug.role_descriptor import Compile, build_descriptors, build_target_spec
from src.search.delta_minimize.contracts import DeltaMinimizeError
from src.search.delta_minimize.delta import MaterializedCandidate
from src.search.delta_minimize.evaluator import (
    CandidateEvaluationConfig,
    EvaluationBackends,
    ParentEvidenceBundle,
    RawCandidateEvidence,
    capture_candidate,
    profile_candidate,
)
from src.search.delta_minimize.objectives import AxisReference, ObjectiveManifest
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


def test_token_equivalent_candidates_reuse_complete_inspection(
    tmp_path: Path,
) -> None:
    first = _candidate(tmp_path, candidate_id="first")
    second_path = tmp_path / "second.c"
    second_text = "int  candidate ( void )  {\n    return 0 ;\n}\n"
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
    assert calls == {"inspect": 1}


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


def test_derived_target_uses_correlated_exact_allocator_namespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump_text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    pcdump = tmp_path / "same.pcdump"
    pcdump.write_text(pcdump_text, encoding="utf-8")
    source = tmp_path / "same.c"
    source.write_text("", encoding="utf-8")
    compile = Compile.from_text(pcdump_text, FUNCTION, "")
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


def test_compiled_candidate_missing_target_function_is_run_level_incomplete(
    tmp_path: Path,
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
        "score_stderr": f"function '{FUNCTION}' not in compiled pcdump",
        "terminal_safe": True,
    }

    store = _store(tmp_path)
    config = _config(tmp_path)
    with pytest.raises(
        DeltaMinimizeError,
        match="^candidate-target-function-missing$",
    ):
        capture_candidate(
            candidate,
            config,
            backends=EvaluationBackends(
                lambda _rows, _config: [row],
                lambda *_args, **_kwargs: pytest.fail(),
            ),
            store=store,
        )
    assert store.load_evidence(store.evidence_key(candidate, config)) is None


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

    with pytest.raises(DeltaMinimizeError, match="inspector-timeout"):
        capture_candidate(
            candidate,
            _config(tmp_path),
            backends=EvaluationBackends(lambda _rows, _config: [_score_row(candidate, pcdump)], timeout),
            store=store,
        )
    assert store.load_evidence(store.evidence_key(candidate, _config(tmp_path))) is None


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
