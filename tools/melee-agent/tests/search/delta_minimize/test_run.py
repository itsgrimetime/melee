from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from src.search.delta_minimize.contracts import AxisDistances, CandidateProfile, DeltaMinimizeError
from src.search.delta_minimize.delta import DeltaAtom, DeltaManifest
from src.search.delta_minimize.evaluator import EvaluationBackends, RawCandidateEvidence
from src.search.delta_minimize.objectives import AxisReference, ObjectiveManifest
from src.search.delta_minimize.run import (
    DeltaMinimizeBackends,
    DeltaMinimizeConfig,
    run_delta_minimize,
)

LEFT = "int f(void) {\n int a = 1;\n int b = 2;\n return a+b;\n}\n"
RIGHT = "int f(void) {\n int a = 3;\n int b = 4;\n return a+b;\n}\n"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _config(tmp_path: Path, **changes: object) -> DeltaMinimizeConfig:
    left = tmp_path / "left.c"
    right = tmp_path / "right.c"
    cflags = tmp_path / "unit.c"
    left.write_text(LEFT, encoding="utf-8")
    right.write_text(RIGHT, encoding="utf-8")
    cflags.write_text("/* unit */\n", encoding="utf-8")
    values = {
        "function": "f",
        "left": left,
        "right": right,
        "out_dir": tmp_path / "out",
        "max_candidates": 64,
        "target_path": None,
        "donor_overrides": {},
        "include_objobjects": True,
        "melee_root": tmp_path,
        "cflags_from": cflags,
    }
    values.update(changes)
    return DeltaMinimizeConfig(**values)


def _objective() -> ObjectiveManifest:
    references = {
        axis: AxisReference("absolute", f"{axis}-artifact", None, "fixture", False)
        for axis in ("opcode", "color", "objobjects", "stack-homes")
    }
    return ObjectiveManifest(
        schema_version="delta-minimize-objectives.v1",
        function="f",
        class_id=0,
        target_spec={"fixture": True},
        desired_phys={1: 3},
        color_donor="left",
        objobject_donor="left",
        stack_home_donor="right",
        references=references,
    )


class _CountingFixture:
    def __init__(
        self,
        tmp_path: Path,
        *,
        incomplete_mask: int | None = None,
        rejected_mask: int | None = None,
        infrastructure_mask: int | None = None,
        parent_infrastructure: bool = False,
    ):
        self.tmp_path = tmp_path
        self.incomplete_mask = incomplete_mask
        self.rejected_mask = rejected_mask
        self.infrastructure_mask = infrastructure_mask
        self.parent_infrastructure = parent_infrastructure
        self.parent_calls = 0
        self.parent_objective_calls = 0
        self.infer_calls = 0
        self.score_calls = 0
        self.inspect_calls = 0
        self.captured_sources: dict[int, bytes] = {}

    def parent_provenance(self, _config):
        return {
            "cflags_hash": "cflags",
            "compiler_fingerprint": "compiler",
            "expected_object_hash": "expected-object",
            "parser_schema_hash": "parsers",
            "inspector_version": "inspector-v1",
        }

    def capture_parent(self, candidate, config, _store):
        self.parent_calls += 1
        if self.parent_infrastructure:
            raise DeltaMinimizeError("parent-score-infrastructure")
        pcdump = self.tmp_path / f"{candidate.candidate_id}.pcdump"
        pcdump.write_text(f"pcdump {candidate.candidate_id}\n", encoding="utf-8")
        return RawCandidateEvidence(
            candidate_id=candidate.candidate_id,
            mask=candidate.mask,
            source_path=str(candidate.source_path),
            source_hash=candidate.source_hash,
            compile_status="compiled",
            viable=True,
            pcdump_path=str(pcdump),
            checkdiff_evidence=None,
            inspect_text="FUNCTION: f\nFrontend: OBJOBJECTS\n" if config.include_objobjects else None,
            compiler_stderr="",
            inspection_mode="objobjects" if config.include_objobjects else "no-objobjects",
            pcdump_hash=hashlib.sha256(pcdump.read_bytes()).hexdigest(),
        )

    def parent_objective(self, raw, side, _config):
        self.parent_objective_calls += 1
        return (side, raw.source_hash)

    def infer_objective(self, _left, _right, _config):
        self.infer_calls += 1
        return _objective()

    def score_rows(self, rows, _config):
        self.score_calls += 1
        row = rows[0]
        candidate_id = row["candidate_id"]
        mask = int(candidate_id.split("-")[1], 2)
        source = Path(row["source_file"])
        self.captured_sources[mask] = source.read_bytes()
        if mask == self.infrastructure_mask:
            return [{**row, "score_error_kind": "infrastructure", "error": "compiler unavailable"}]
        if mask == self.rejected_mask:
            return [
                {
                    **row,
                    "score_error_kind": "candidate",
                    "error": "compile rejected",
                    "score_stderr": "mwcceppc_debug.exe compiler error: syntax error",
                }
            ]
        pcdump = self.tmp_path / f"{candidate_id}.pcdump"
        pcdump.write_text(f"pcdump {mask}\n", encoding="utf-8")
        return [
            {
                **row,
                "pcdump_path": str(pcdump),
                "score_returncode": 0,
                "score_error_kind": None,
                "score_stderr": "",
                "checkdiff_evidence": {
                    "match": mask == 2,
                    "target_asm": ["+000: 38 60 00 00 li r3,0"],
                    "current_asm": ["+000: 38 80 00 00 li r4,0"],
                },
            }
        ]

    def inspect_source(self, _source, function, _output, **_kwargs):
        self.inspect_calls += 1
        return f"FUNCTION: {function}\nFrontend: OBJOBJECTS\n"

    def profile(self, raw, _objective, *, parents):
        assert parents.left.candidate_id == "parent-left"
        if not raw.viable:
            return CandidateProfile(
                candidate_id=raw.candidate_id,
                mask=raw.mask,
                source_hash=raw.source_hash,
                source_path=raw.source_path,
                viable=False,
                compile_status="rejected",
                axes=None,
                complete=True,
                blockers=raw.blockers,
            )
        complete = raw.mask != self.incomplete_mask
        return CandidateProfile(
            candidate_id=raw.candidate_id,
            mask=raw.mask,
            source_hash=raw.source_hash,
            source_path=raw.source_path,
            viable=True,
            compile_status="compiled",
            axes=AxisDistances(
                (raw.mask, 0),
                (3 - raw.mask, 0, 0, 0, 0, 0),
                (raw.mask % 2, 0),
                (raw.mask // 2, 0, 0, 0),
            )
            if complete
            else None,
            complete=complete,
            exact_object_match=bool(raw.checkdiff_evidence and raw.checkdiff_evidence.get("match") is True),
            blockers=() if complete else ("missing-inspect-text",),
        )

    def backends(self) -> DeltaMinimizeBackends:
        return DeltaMinimizeBackends(
            parent_provenance=self.parent_provenance,
            capture_parent=self.capture_parent,
            parent_objective=self.parent_objective,
            infer_objective=self.infer_objective,
            evaluation=EvaluationBackends(self.score_rows, self.inspect_source),
            profile_candidate=self.profile,
        )


def test_run_evaluates_every_legal_mask_and_resumes(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)

    first = run_delta_minimize(config, backends=fixture.backends())
    assert first.candidate_counts == {"legal": 4, "viable": 4, "complete": 4}
    assert fixture.score_calls == 4
    assert fixture.parent_calls == 2
    assert fixture.parent_objective_calls == 2
    assert fixture.infer_calls == 1
    second = run_delta_minimize(config, backends=fixture.backends())

    assert second.to_dict() == first.to_dict()
    assert fixture.score_calls == 4
    assert fixture.parent_calls == 2
    assert fixture.parent_objective_calls == 2
    assert fixture.infer_calls == 1
    assert second.cache_stats == {"parent_entries": 2, "candidate_entries": 4}


def test_run_materializes_only_parent_deltas_and_reproduces_both_endpoints(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)

    result = run_delta_minimize(_config(tmp_path), backends=fixture.backends())

    assert result.candidate_counts["legal"] == len(fixture.captured_sources) == 4
    assert fixture.captured_sources[0] == LEFT.encode()
    assert fixture.captured_sources[3] == RIGHT.encode()
    assert all(b"1" in source or b"3" in source for source in fixture.captured_sources.values())
    assert all(b"2" in source or b"4" in source for source in fixture.captured_sources.values())


def test_resume_revalidates_stale_parent_artifacts(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    first = run_delta_minimize(config, backends=fixture.backends())
    (tmp_path / "parent-left.pcdump").unlink()

    second = run_delta_minimize(config, backends=fixture.backends())

    assert second.to_dict() == first.to_dict()
    assert fixture.parent_calls == 3
    assert fixture.score_calls == 4


def test_one_incomplete_viable_mask_blocks_the_whole_frontier(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path, incomplete_mask=2)

    result = run_delta_minimize(_config(tmp_path), backends=fixture.backends())

    assert result.status == "incomplete"
    assert result.exact_four_axis is False
    assert result.pareto is None
    assert result.candidate_counts == {"legal": 4, "viable": 4, "complete": 3}
    assert "missing-inspect-text" in result.blockers


def test_compile_rejected_mask_stays_in_ledger_but_not_viable_count(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path, rejected_mask=1)

    result = run_delta_minimize(_config(tmp_path), backends=fixture.backends())

    assert result.candidate_counts == {"legal": 4, "viable": 3, "complete": 3}
    rejected = next(row for row in result.candidates if row["mask"] == 1)
    assert rejected["profile"]["compile_status"] == "rejected"
    assert rejected["profile"]["viable"] is False
    assert result.pareto is not None
    assert "mask-01" not in result.pareto.candidate_ids


def test_infrastructure_failure_writes_resumable_incomplete_result(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path, infrastructure_mask=2)
    config = _config(tmp_path)

    result = run_delta_minimize(config, backends=fixture.backends())

    assert result.status == "incomplete"
    assert result.candidate_counts["legal"] == 4
    assert result.pareto is None
    assert "candidate-score-infrastructure" in result.blockers
    assert (config.out_dir / "candidates.json").is_file()
    assert (config.out_dir / "result.json").is_file()


def test_parent_infrastructure_failure_writes_early_incomplete_result(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path, parent_infrastructure=True)
    config = _config(tmp_path)

    result = run_delta_minimize(config, backends=fixture.backends())

    assert result.status == "incomplete"
    assert result.candidate_counts == {"legal": 0, "viable": 0, "complete": 0}
    assert result.objective_manifest == {}
    assert result.delta_manifest == {}
    assert result.blockers == ("parent-score-infrastructure",)
    assert (config.out_dir / "result.json").is_file()


def test_no_objobjects_is_provisional_and_never_claims_joint_solution(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)

    result = run_delta_minimize(
        _config(tmp_path, include_objobjects=False),
        backends=fixture.backends(),
    )

    assert result.status == "provisional"
    assert result.exact_four_axis is False
    assert result.pareto is not None
    assert result.pareto.status == "provisional"
    assert result.pareto.joint_solutions == ()
    assert result.pareto.joint_zero_all_candidate_ids == ()
    assert fixture.inspect_calls == 0


def test_exact_object_match_controls_matched_status_not_proxy_distance(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)

    result = run_delta_minimize(_config(tmp_path), backends=fixture.backends())

    assert result.status == "matched"
    assert result.pareto is not None
    assert result.pareto.exact_match_candidate_ids == ("mask-10",)


def test_budget_overflow_writes_manifest_before_compiling_nothing(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path, max_candidates=3)

    with pytest.raises(DeltaMinimizeError, match="candidate-budget-exceeded") as error:
        run_delta_minimize(config, backends=fixture.backends())

    assert error.value.details == {"required": 4, "limit": 3}
    assert fixture.score_calls == 0
    assert (config.out_dir / "delta-manifest.json").is_file()
    assert not (config.out_dir / "pareto.json").exists()


def test_atom_safety_ceiling_fails_before_enumeration(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    manifest = DeltaManifest(
        "delta-manifest.v1",
        "f",
        _hash(LEFT),
        _hash(RIGHT),
        tuple(DeltaAtom(f"a{index}", "expression", ()) for index in range(21)),
    )
    backends = replace(fixture.backends(), extract_manifest=lambda *_args, **_kwargs: manifest)

    with pytest.raises(DeltaMinimizeError, match="atom-space-too-large"):
        run_delta_minimize(_config(tmp_path), backends=backends)

    assert fixture.score_calls == 0
