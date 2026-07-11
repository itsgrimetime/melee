from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

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
    assert calls == {"score": 2, "inspect": 2}


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
