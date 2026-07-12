from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.search.delta_minimize import run as run_module
from src.search.delta_minimize.contracts import AxisDistances, CandidateProfile, DeltaMinimizeError
from src.search.delta_minimize.delta import DeltaAtom, DeltaManifest
from src.search.delta_minimize.evaluator import EvaluationBackends, RawCandidateEvidence
from src.search.delta_minimize.objectives import (
    COLOR_TARGET_SCHEMA_V2,
    OBJECTIVE_MANIFEST_SCHEMA,
    ROLE_NAMESPACE_SCHEMA,
    AxisReference,
    ObjectiveManifest,
)
from src.search.delta_minimize.run import (
    DeltaMinimizeBackends,
    DeltaMinimizeConfig,
    default_delta_minimize_backends,
    run_delta_minimize,
)

LEFT = "int f(void) {\n int a = 1;\n int b = 2;\n return a+b;\n}\n"
RIGHT = "int f(void) {\n int a = 3;\n int b = 4;\n return a+b;\n}\n"


def test_parent_opcode_evidence_ignores_blank_checkdiff_terminators() -> None:
    assert run_module._validated_asm_lines(["+000: 38 60 00 00 li r3,0", ""]) == ("+000: 38 60 00 00 li r3,0",)


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


def _objective(
    *,
    desired_physical: int = 3,
    donor_overrides: dict[str, str] | None = None,
) -> ObjectiveManifest:
    overrides = donor_overrides or {}
    color_donor = overrides.get("color", "left")
    objobject_donor = overrides.get("objobjects", color_donor)
    stack_donor = overrides.get("stack-homes", "right")
    references = {
        "opcode": AxisReference(
            "absolute",
            "opcode-artifact",
            None,
            "expected-assembly-absolute;equal-parent-distance",
            False,
        ),
        "color": AxisReference(
            "mixed",
            "color-artifact",
            color_donor,
            "cross-parent-round-trip-derived-target;"
            + ("explicit-color-donor-override" if "color" in overrides else "lower-desired-assignment-distance"),
            "color" in overrides,
        ),
        "objobjects": AxisReference(
            "proxy",
            "objobjects-artifact",
            objobject_donor,
            ("explicit-objobject-donor-override" if "objobjects" in overrides else "inherits-selected-color-donor"),
            "objobjects" in overrides,
        ),
        "stack-homes": AxisReference(
            "absolute",
            "stack-homes-artifact",
            stack_donor,
            (
                "explicit-stack-home-donor-override"
                if "stack-homes" in overrides
                else "strictly-lower-stack-home-distance"
            ),
            "stack-homes" in overrides,
        ),
    }
    return ObjectiveManifest(
        schema_version=OBJECTIVE_MANIFEST_SCHEMA,
        function="f",
        class_id=0,
        target_spec={
            "function": "f",
            "target_kind": "force_proof_proxy",
            "target_coverage": 1.0,
            "causal_closure": False,
            "provenance": {"inference": "parent-register-diff", "parent": "left"},
            "roles": [
                {
                    "original_ig": 1,
                    "desired_phys": desired_physical,
                    "class_id": 0,
                    "descriptor": None,
                    "role_order_rank": 0,
                }
            ],
        },
        desired_phys={1: desired_physical},
        color_donor=color_donor,
        objobject_donor=objobject_donor,
        stack_home_donor=stack_donor,
        references=references,
    )


def _v2_objective() -> ObjectiveManifest:
    objective = _objective()
    provenance = {
        "schema_version": COLOR_TARGET_SCHEMA_V2,
        "baseline_side": "left",
        "baseline_dump": "/evidence/left.pcdump",
        "baseline_dump_sha256": "b" * 64,
        "parent_role_bindings": {
            "left": {
                "source_sha256": "1" * 64,
                "pcdump_sha256": "b" * 64,
                "canonical_to_parent": {"1": 1},
            },
            "right": {
                "source_sha256": "2" * 64,
                "pcdump_sha256": "3" * 64,
                "canonical_to_parent": {"1": 7},
            },
        },
        "namespace_schema": ROLE_NAMESPACE_SCHEMA,
    }
    return replace(
        objective,
        target_spec={**dict(objective.target_spec), "provenance": provenance},
        references={
            **dict(objective.references),
            "color": replace(
                objective.references["color"],
                inference_reason="explicit-versioned-color-target;lower-desired-assignment-distance",
            ),
        },
    )


def test_v2_objective_provenance_round_trips_with_exact_bindings() -> None:
    payload = _v2_objective().to_dict()

    restored = run_module._objective_from_dict(payload, function="f")

    assert restored.to_dict() == payload
    provenance = restored.target_spec["provenance"]
    assert tuple(provenance["parent_role_bindings"]) == ("left", "right")
    assert provenance["namespace_schema"] == ROLE_NAMESPACE_SCHEMA


@pytest.mark.parametrize(
    "mutation",
    (
        "left-source-hash",
        "right-pcdump-hash",
        "left-role-map",
        "right-role-map",
        "baseline-side",
        "baseline-dump-hash",
        "namespace-schema",
        "added-field",
        "removed-field",
    ),
)
def test_v2_objective_provenance_tampering_fails_closed(mutation: str) -> None:
    payload = deepcopy(_v2_objective().to_dict())
    provenance = payload["target_spec"]["provenance"]
    bindings = provenance["parent_role_bindings"]
    if mutation == "left-source-hash":
        bindings["left"]["source_sha256"] = "not-a-hash"
    elif mutation == "right-pcdump-hash":
        bindings["right"]["pcdump_sha256"] = "not-a-hash"
    elif mutation == "left-role-map":
        bindings["left"]["canonical_to_parent"] = {"1": 2}
    elif mutation == "right-role-map":
        bindings["right"]["canonical_to_parent"] = {"2": 7}
    elif mutation == "baseline-side":
        provenance["baseline_side"] = "middle"
    elif mutation == "baseline-dump-hash":
        provenance["baseline_dump_sha256"] = "4" * 64
    elif mutation == "namespace-schema":
        provenance["namespace_schema"] = "delta-minimize-role-namespace.v0"
    elif mutation == "added-field":
        provenance["unexpected"] = True
    else:
        del provenance["namespace_schema"]

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-manifest$"):
        run_module._objective_from_dict(payload, function="f")


@pytest.mark.parametrize("side", ("left", "right"))
def test_v2_binding_changes_objective_content_epoch(side: str) -> None:
    original = _v2_objective().to_dict()
    changed = deepcopy(original)
    changed["target_spec"]["provenance"]["parent_role_bindings"][side]["source_sha256"] = "9" * 64

    assert run_module._hash_json(changed) != run_module._hash_json(original)


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
        self.parent_generation = 1
        self.parent_checkdiff = False
        self.expected_object_hash = "expected-object"
        self.objective_physical = 3
        self.captured_sources: dict[int, bytes] = {}
        self.target_paths: list[Path] = []

    def parent_provenance(self, _config):
        return {
            "cflags_hash": "cflags",
            "compiler_fingerprint": "compiler",
            "expected_object_hash": self.expected_object_hash,
            "parser_schema_hash": "parsers",
            "inspector_version": "inspector-v1",
        }

    def capture_parent(self, candidate, config, _store):
        self.parent_calls += 1
        if self.parent_infrastructure:
            raise DeltaMinimizeError("parent-score-infrastructure")
        pcdump = self.tmp_path / f"{candidate.candidate_id}.pcdump"
        pcdump.write_text(
            f"pcdump {candidate.candidate_id} generation {self.parent_generation}\n",
            encoding="utf-8",
        )
        return RawCandidateEvidence(
            candidate_id=candidate.candidate_id,
            mask=candidate.mask,
            source_path=str(candidate.source_path),
            source_hash=candidate.source_hash,
            compile_status="compiled",
            viable=True,
            pcdump_path=str(pcdump),
            checkdiff_evidence={"function": config.function} if self.parent_checkdiff else None,
            inspect_text="FUNCTION: f\nFrontend: OBJOBJECTS\n" if config.include_objobjects else None,
            compiler_stderr="",
            inspection_mode="objobjects" if config.include_objobjects else "no-objobjects",
            pcdump_hash=hashlib.sha256(pcdump.read_bytes()).hexdigest(),
        )

    def parent_objective(self, raw, side, _config):
        self.parent_objective_calls += 1
        return (side, raw.source_hash)

    def infer_objective(self, _left, _right, config):
        self.infer_calls += 1
        return _objective(
            desired_physical=self.objective_physical,
            donor_overrides=dict(config.donor_overrides),
        )

    def score_rows(self, rows, score_config):
        self.score_calls += 1
        assert score_config.target is not None
        self.target_paths.append(score_config.target)
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
    assert fixture.parent_objective_calls == 4
    assert fixture.infer_calls == 2
    assert second.cache_stats == {"parent_entries": 2, "candidate_entries": 4}


def test_run_preserves_actionable_objective_ambiguity(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    backends = replace(
        fixture.backends(),
        infer_objective=lambda *_args: (_ for _ in ()).throw(DeltaMinimizeError("ambiguous-color-target")),
    )

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        run_delta_minimize(_config(tmp_path), backends=backends)


def test_resume_rejects_valid_shape_delta_dependency_cache_mutation(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    first = run_delta_minimize(config, backends=fixture.backends())
    manifest_path = config.out_dir / "delta-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["atoms"][1]["requires"] = [manifest["atoms"][0]["atom_id"]]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-delta-manifest$"):
        run_delta_minimize(config, backends=fixture.backends())

    assert first.candidate_counts == {"legal": 4, "viable": 4, "complete": 4}
    assert fixture.parent_calls == 2
    assert fixture.score_calls == 4


@pytest.mark.parametrize(
    "mutation",
    ("atom", "replacement", "anchor", "blockers"),
)
def test_resume_rejects_context_matching_delta_manifest_semantic_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())
    manifest_path = config.out_dir / "delta-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "atom":
        manifest["atoms"][0]["atom_id"] += "-tampered"
    elif mutation == "replacement":
        manifest["atoms"][0]["patches"][0]["right_text"] += " "
    elif mutation == "anchor":
        manifest["atoms"][0]["patches"][0]["anchor_symbol"] += ":tampered"
    elif mutation == "blockers":
        manifest["blockers"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-delta-manifest$"):
        run_delta_minimize(config, backends=fixture.backends())

    assert fixture.parent_calls == 2
    assert fixture.score_calls == 4


@pytest.mark.parametrize("mutation", ("schema", "function", "left-hash", "right-hash"))
def test_resume_rejects_or_atomically_replaces_delta_manifest_identity_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    first = run_delta_minimize(config, backends=fixture.backends())
    manifest_path = config.out_dir / "delta-manifest.json"
    canonical = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutated = json.loads(json.dumps(canonical))
    if mutation == "schema":
        mutated["schema_version"] = "delta-manifest.v0"
    elif mutation == "function":
        mutated["function"] = "other"
    elif mutation == "left-hash":
        mutated["left_hash"] = "0" * 64
    elif mutation == "right-hash":
        mutated["right_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(mutated), encoding="utf-8")

    if mutation == "schema":
        with pytest.raises(DeltaMinimizeError, match="^corrupt-delta-manifest$"):
            run_delta_minimize(config, backends=fixture.backends())
    else:
        second = run_delta_minimize(config, backends=fixture.backends())
        assert second.to_dict() == first.to_dict()
        assert json.loads(manifest_path.read_text(encoding="utf-8")) == canonical

    assert fixture.parent_calls == 2
    assert fixture.score_calls == 4


def test_unchanged_delta_manifest_rederives_locally_without_external_resume_work(
    tmp_path: Path,
) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    base = fixture.backends()
    extract_calls = 0

    def extract(left: str, right: str, *, function: str) -> DeltaManifest:
        nonlocal extract_calls
        extract_calls += 1
        return base.extract_manifest(left, right, function=function)

    backends = replace(base, extract_manifest=extract)
    first = run_delta_minimize(config, backends=backends)
    second = run_delta_minimize(config, backends=backends)

    assert second.to_dict() == first.to_dict()
    assert extract_calls == 2
    assert fixture.parent_calls == 2
    assert fixture.score_calls == 4


def test_extractor_schema_upgrade_rekeys_candidates_with_changed_atom_order(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    base = fixture.backends()

    def old_extract(left: str, right: str, *, function: str) -> DeltaManifest:
        return replace(base.extract_manifest(left, right, function=function), schema_version="delta-manifest.v1")

    first = run_delta_minimize(config, backends=replace(base, extract_manifest=old_extract))
    assert first.candidate_counts == {"legal": 4, "viable": 4, "complete": 4}

    def new_extract(left: str, right: str, *, function: str) -> DeltaManifest:
        manifest = base.extract_manifest(left, right, function=function)
        return replace(manifest, atoms=tuple(reversed(manifest.atoms)))

    second = run_delta_minimize(config, backends=replace(base, extract_manifest=new_extract))

    assert second.candidate_counts == first.candidate_counts
    assert fixture.score_calls == 8
    manifest = json.loads((config.out_dir / "delta-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "delta-manifest.v2"


def test_extractor_schema_upgrade_removes_stale_publications_before_enumeration(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    base = fixture.backends()

    def old_extract(left: str, right: str, *, function: str) -> DeltaManifest:
        return replace(base.extract_manifest(left, right, function=function), schema_version="delta-manifest.v1")

    run_delta_minimize(config, backends=replace(base, extract_manifest=old_extract))
    assert (config.out_dir / "result.json").is_file()
    assert (config.out_dir / "candidates.json").is_file()

    with pytest.raises(DeltaMinimizeError, match="^candidate-budget-exceeded$"):
        run_delta_minimize(
            replace(config, max_candidates=1),
            backends=base,
        )

    assert not (config.out_dir / "result.json").exists()
    assert not (config.out_dir / "candidates.json").exists()
    manifest = json.loads((config.out_dir / "delta-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "delta-manifest.v2"


def test_extractor_schema_upgrade_removes_stale_publications_before_objective_failure(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    base = fixture.backends()

    def old_extract(left: str, right: str, *, function: str) -> DeltaManifest:
        return replace(base.extract_manifest(left, right, function=function), schema_version="delta-manifest.v1")

    run_delta_minimize(config, backends=replace(base, extract_manifest=old_extract))
    assert (config.out_dir / "result.json").is_file()
    assert (config.out_dir / "candidates.json").is_file()

    fixture.expected_object_hash = "new-parent-epoch"
    ambiguous = replace(
        fixture.backends(),
        infer_objective=lambda *_args: (_ for _ in ()).throw(DeltaMinimizeError("ambiguous-color-target")),
    )
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        run_delta_minimize(config, backends=ambiguous)

    assert not (config.out_dir / "result.json").exists()
    assert not (config.out_dir / "candidates.json").exists()
    manifest = json.loads((config.out_dir / "delta-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "delta-manifest.v2"


def test_objective_context_change_removes_stale_publications_before_ambiguity(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())

    fixture.expected_object_hash = "new-parent-epoch"
    ambiguous = replace(
        fixture.backends(),
        infer_objective=lambda *_args: (_ for _ in ()).throw(DeltaMinimizeError("ambiguous-color-target")),
    )
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        run_delta_minimize(config, backends=ambiguous)

    assert not (config.out_dir / "result.json").exists()
    assert not (config.out_dir / "candidates.json").exists()


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


def test_parent_cache_can_require_retained_checkdiff_evidence(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    first = run_delta_minimize(config, backends=fixture.backends())

    fixture.parent_checkdiff = True
    strict = replace(fixture.backends(), parent_requires_checkdiff=True)
    second = run_delta_minimize(config, backends=strict)

    assert second.to_dict() == first.to_dict()
    assert fixture.parent_calls == 4
    assert fixture.score_calls == 4


def test_parent_checkdiff_requirement_validates_fresh_capture(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)

    with pytest.raises(DeltaMinimizeError, match="^invalid-parent-evidence$"):
        run_delta_minimize(
            _config(tmp_path),
            backends=replace(fixture.backends(), parent_requires_checkdiff=True),
        )


def test_production_parent_cache_requires_checkdiff_evidence() -> None:
    assert default_delta_minimize_backends().parent_requires_checkdiff is True


def test_production_objective_adapter_supplies_real_register_diff_deriver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.cli.debug import _derive_force_phys_from_register_diff_lines

    expected = _objective()
    seen: dict[str, object] = {}

    def infer(left, right, **kwargs):
        seen.update(kwargs)
        assert left is left_parent
        assert right is right_parent
        return expected

    left_parent = object()
    right_parent = object()
    monkeypatch.setattr(run_module, "infer_objective_manifest", infer)

    actual = default_delta_minimize_backends().infer_objective(
        left_parent,
        right_parent,
        _config(tmp_path),
    )

    assert actual is expected
    assert seen["target_path"] is None
    assert seen["derive_force_target"] is _derive_force_phys_from_register_diff_lines


def test_changed_expected_object_invalidates_objective_cache(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())

    fixture.expected_object_hash = "new-expected-object"
    run_delta_minimize(config, backends=fixture.backends())

    assert fixture.parent_calls == 4
    assert fixture.parent_objective_calls == 4
    assert fixture.infer_calls == 2


def test_refreshed_parent_profile_invalidates_objective_cache(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())

    (tmp_path / "parent-left.pcdump").write_text("stale profile\n", encoding="utf-8")
    fixture.parent_generation = 2
    run_delta_minimize(config, backends=fixture.backends())

    assert fixture.parent_calls == 3
    assert fixture.parent_objective_calls == 4
    assert fixture.infer_calls == 2


def test_changed_valid_objective_starts_a_new_target_epoch(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    first = run_delta_minimize(config, backends=fixture.backends())
    first_target = fixture.target_paths[-1]

    fixture.expected_object_hash = "new-expected-object"
    fixture.objective_physical = 4
    second = run_delta_minimize(config, backends=fixture.backends())
    second_target = fixture.target_paths[-1]

    assert first.objective_manifest["desired_phys"] == {"1": 3}
    assert second.objective_manifest["desired_phys"] == {"1": 4}
    assert first_target != second_target
    assert json.loads(first_target.read_text(encoding="utf-8"))["virtuals"] == {"1": 3}
    assert json.loads(second_target.read_text(encoding="utf-8"))["virtuals"] == {"1": 4}
    assert fixture.score_calls == 8
    assert len(set(fixture.target_paths[:4])) == 1
    assert len(set(fixture.target_paths[4:])) == 1

    current = json.loads((config.out_dir / "objective" / "color-target-current.json").read_text())
    current_target = config.out_dir / current["artifact"]
    assert current_target.parent.name == "color-targets"
    assert current["sha256"] == current_target.stem
    assert json.loads(current_target.read_text(encoding="utf-8"))["roles"][0]["desired_phys"] == 4

    unchanged = run_delta_minimize(config, backends=fixture.backends())
    assert unchanged.to_dict() == second.to_dict()
    assert fixture.score_calls == 8


def test_objective_cache_persists_context_with_valid_digest(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())

    payload = json.loads((config.out_dir / "objective-inputs.json").read_text(encoding="utf-8"))
    context = payload["context"]
    canonical = json.dumps(context, sort_keys=True, separators=(",", ":")).encode()

    assert payload["schema_version"] == "delta-minimize-objective-inputs.v3"
    assert payload["context_digest"] == hashlib.sha256(canonical).hexdigest()
    manifest = json.loads((config.out_dir / "objective-manifest.json").read_text(encoding="utf-8"))
    manifest_blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    assert payload["objective_manifest_digest"] == hashlib.sha256(manifest_blob).hexdigest()
    assert context["parents"]["left"]["pcdump_hash"]
    assert context["expected_object_hash"] == "expected-object"
    assert context["parser_schema_hash"] == "parsers"


def test_malformed_objective_cache_context_fails_closed(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())
    cache_path = config.out_dir / "objective-inputs.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["context_digest"] = "0" * 64
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-cache-context$"):
        run_delta_minimize(config, backends=fixture.backends())


def test_pre_binding_objective_input_schema_is_rejected(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())
    cache_path = config.out_dir / "objective-inputs.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "delta-minimize-objective-inputs.v2"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-cache-context$"):
        run_delta_minimize(config, backends=fixture.backends())


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "function",
        "axis-deletion",
        "axis-extra",
        "donor-value",
        "donor-type",
        "class-type",
        "class-domain",
        "desired-phys-range",
        "descriptor-ig-bool",
        "descriptor-assigned-range",
        "reference-artifact-type",
        "reference-reason-type",
        "reference-override-type",
        "reference-unresolved-type",
        "target-provenance-type",
        "target-payload",
    ),
)
def test_invalid_integrity_bound_objective_manifest_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())
    manifest_path = config.out_dir / "objective-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "schema":
        manifest["schema_version"] = "delta-minimize-objectives.v1"
    elif mutation == "function":
        manifest["function"] = "other"
    elif mutation == "axis-deletion":
        del manifest["references"]["opcode"]
    elif mutation == "axis-extra":
        manifest["references"]["extra"] = dict(manifest["references"]["opcode"])
    elif mutation == "donor-value":
        manifest["objobject_donor"] = "both"
    elif mutation == "donor-type":
        manifest["color_donor"] = 1
    elif mutation == "class-type":
        manifest["class_id"] = True
    elif mutation == "class-domain":
        manifest["class_id"] = 2
        manifest["target_spec"]["roles"][0]["class_id"] = 2
    elif mutation == "desired-phys-range":
        manifest["desired_phys"]["1"] = 32
        manifest["target_spec"]["roles"][0]["desired_phys"] = 32
    elif mutation in {"descriptor-ig-bool", "descriptor-assigned-range"}:
        manifest["target_spec"]["roles"][0]["descriptor"] = {
            "ig_idx": True if mutation == "descriptor-ig-bool" else 1,
            "first_def_sig": "li r#,0",
            "use_site_multiset": [["add", 1]],
            "is_param": False,
            "var_name": "value",
            "var_confidence": "high",
            "assigned_reg": 32 if mutation == "descriptor-assigned-range" else 3,
            "live_range": [0, 1],
            "use_count": 1,
            "spilled": False,
        }
    elif mutation == "reference-artifact-type":
        manifest["references"]["opcode"]["reference_artifact"] = 1
    elif mutation == "reference-reason-type":
        manifest["references"]["opcode"]["inference_reason"] = 1
    elif mutation == "reference-override-type":
        manifest["references"]["color"]["override"] = 1
    elif mutation == "reference-unresolved-type":
        manifest["references"]["stack-homes"]["unresolved"] = [1]
    elif mutation == "target-provenance-type":
        manifest["target_spec"]["provenance"] = {"inference": 1, "parent": "left"}
    elif mutation == "target-payload":
        manifest["target_spec"]["roles"][0]["desired_phys"] = -1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    inputs_path = config.out_dir / "objective-inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    inputs["objective_manifest_digest"] = hashlib.sha256(canonical).hexdigest()
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-manifest$"):
        run_delta_minimize(config, backends=fixture.backends())


@pytest.mark.parametrize(
    ("overrides", "mutation"),
    (
        ({}, "default-objobject-donor-diverges"),
        ({}, "spurious-color-override"),
        ({"color": "left"}, "missing-color-override"),
        ({"color": "right"}, "color-context-donor-mismatch"),
        ({"objobjects": "right"}, "missing-objobject-override"),
        ({"objobjects": "right"}, "objobject-context-donor-mismatch"),
        ({"stack-homes": "right"}, "missing-stack-override"),
        ({"stack-homes": "left"}, "stack-context-donor-mismatch"),
        ({}, "color-inference-reason-mismatch"),
        ({}, "objobject-inference-reason-mismatch"),
        ({}, "stack-inference-reason-mismatch"),
    ),
)
def test_cached_objective_donor_semantics_are_bound_to_context(
    tmp_path: Path,
    overrides: dict[str, str],
    mutation: str,
) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path, donor_overrides=overrides)
    run_delta_minimize(config, backends=fixture.backends())
    manifest_path = config.out_dir / "objective-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "default-objobject-donor-diverges":
        manifest["objobject_donor"] = "right"
        manifest["references"]["objobjects"]["donor"] = "right"
    elif mutation == "spurious-color-override":
        manifest["references"]["color"]["override"] = True
        manifest["references"]["color"]["inference_reason"] = (
            "cross-parent-round-trip-derived-target;explicit-color-donor-override"
        )
    elif mutation == "missing-color-override":
        manifest["references"]["color"]["override"] = False
        manifest["references"]["color"]["inference_reason"] = (
            "cross-parent-round-trip-derived-target;lower-desired-assignment-distance"
        )
    elif mutation == "color-context-donor-mismatch":
        manifest["color_donor"] = "left"
        manifest["references"]["color"]["donor"] = "left"
    elif mutation == "missing-objobject-override":
        manifest["references"]["objobjects"]["override"] = False
        manifest["references"]["objobjects"]["inference_reason"] = "inherits-selected-color-donor"
    elif mutation == "objobject-context-donor-mismatch":
        manifest["objobject_donor"] = "left"
        manifest["references"]["objobjects"]["donor"] = "left"
    elif mutation == "missing-stack-override":
        manifest["references"]["stack-homes"]["override"] = False
        manifest["references"]["stack-homes"]["inference_reason"] = "strictly-lower-stack-home-distance"
    elif mutation == "stack-context-donor-mismatch":
        manifest["stack_home_donor"] = "right"
        manifest["references"]["stack-homes"]["donor"] = "right"
    elif mutation == "color-inference-reason-mismatch":
        manifest["references"]["color"]["inference_reason"] = (
            "cross-parent-round-trip-derived-target;explicit-color-donor-override"
        )
    elif mutation == "objobject-inference-reason-mismatch":
        manifest["references"]["objobjects"]["inference_reason"] = "explicit-objobject-donor-override"
    elif mutation == "stack-inference-reason-mismatch":
        manifest["references"]["stack-homes"]["inference_reason"] = "explicit-stack-home-donor-override"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    inputs_path = config.out_dir / "objective-inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    inputs["objective_manifest_digest"] = hashlib.sha256(canonical).hexdigest()
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-manifest$"):
        run_delta_minimize(config, backends=fixture.backends())


def test_valid_cached_objective_with_all_donor_overrides_is_reused(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(
        tmp_path,
        donor_overrides={"color": "right", "objobjects": "left", "stack-homes": "left"},
    )

    first = run_delta_minimize(config, backends=fixture.backends())
    second = run_delta_minimize(config, backends=fixture.backends())

    assert second.to_dict() == first.to_dict()
    assert fixture.parent_calls == 2
    assert fixture.score_calls == 4
    assert fixture.parent_objective_calls == 4
    assert fixture.infer_calls == 2


@pytest.mark.parametrize(
    "mutation",
    (
        "target-parent",
        "target-explicit-provenance",
        "target-coverage",
        "target-causal-closure",
        "target-role-identity",
        "target-role-rank",
        "target-role-descriptor",
        "target-class",
        "target-physical",
        "opcode-artifact",
        "opcode-donor",
        "color-artifact",
        "color-donor",
        "objobject-artifact",
        "stack-artifact",
        "stack-donor",
        "stack-reference-kind",
    ),
)
def test_cached_objective_valid_shape_is_bound_to_current_parent_semantics(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())
    manifest_path = config.out_dir / "objective-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "target-parent":
        manifest["target_spec"]["provenance"]["parent"] = "right"
    elif mutation == "target-explicit-provenance":
        manifest["target_spec"]["provenance"] = {
            "schema_version": "delta-minimize-color-target.v1",
            "baseline_dump": str(tmp_path / "parent-left.pcdump"),
        }
        manifest["references"]["color"]["inference_reason"] = (
            "explicit-versioned-color-target;lower-desired-assignment-distance"
        )
    elif mutation == "target-coverage":
        manifest["target_spec"]["target_coverage"] = 0.5
    elif mutation == "target-causal-closure":
        manifest["target_spec"]["causal_closure"] = True
    elif mutation == "target-role-identity":
        manifest["desired_phys"] = {"2": 3}
        manifest["target_spec"]["roles"][0]["original_ig"] = 2
    elif mutation == "target-role-rank":
        manifest["target_spec"]["roles"][0]["role_order_rank"] = 1
    elif mutation == "target-role-descriptor":
        manifest["target_spec"]["roles"][0]["descriptor"] = {
            "ig_idx": 1,
            "first_def_sig": "li r#,0",
            "use_site_multiset": [["add", 1]],
            "is_param": False,
            "var_name": "value",
            "var_confidence": "high",
            "assigned_reg": 3,
            "live_range": [0, 1],
            "use_count": 1,
            "spilled": False,
        }
    elif mutation == "target-class":
        manifest["class_id"] = 1
        manifest["target_spec"]["roles"][0]["class_id"] = 1
    elif mutation == "target-physical":
        manifest["desired_phys"]["1"] = 4
        manifest["target_spec"]["roles"][0]["desired_phys"] = 4
    elif mutation == "opcode-artifact":
        manifest["references"]["opcode"]["reference_artifact"] = "unbound-expected-object"
    elif mutation == "opcode-donor":
        manifest["references"]["opcode"]["donor"] = "left"
        manifest["references"]["opcode"]["inference_reason"] = "expected-assembly-absolute;left-parent-closer"
    elif mutation == "color-artifact":
        manifest["references"]["color"]["reference_artifact"] = "unbound-color-profile"
    elif mutation == "color-donor":
        manifest["color_donor"] = "right"
        manifest["objobject_donor"] = "right"
        manifest["references"]["color"]["donor"] = "right"
        manifest["references"]["objobjects"]["donor"] = "right"
    elif mutation == "objobject-artifact":
        manifest["references"]["objobjects"]["reference_artifact"] = "unbound-inspect-output"
    elif mutation == "stack-artifact":
        manifest["references"]["stack-homes"]["reference_artifact"] = "unbound-stack-profile"
    elif mutation == "stack-donor":
        manifest["stack_home_donor"] = "left"
        manifest["references"]["stack-homes"]["donor"] = "left"
    elif mutation == "stack-reference-kind":
        manifest["references"]["stack-homes"]["reference_kind"] = "mixed"
        manifest["references"]["stack-homes"]["unresolved"] = ["proxy-home"]

    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    inputs_path = config.out_dir / "objective-inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    inputs["objective_manifest_digest"] = hashlib.sha256(canonical).hexdigest()
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-manifest$"):
        run_delta_minimize(config, backends=fixture.backends())

    # Resume validation may rederive from retained parents, but it must not
    # recapture compiler/inspector evidence or evaluate candidates.
    assert fixture.parent_calls == 2
    assert fixture.score_calls == 4


@pytest.mark.parametrize(
    "overrides",
    (
        {"opcode": "left"},
        {"color": "middle"},
        {"stack_homes": "left"},
        {"color": True},
    ),
)
def test_run_config_rejects_unsupported_donor_overrides(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(DeltaMinimizeError, match="^invalid-delta-minimize-config$"):
        _config(tmp_path, donor_overrides=overrides)


@pytest.mark.parametrize("mutation", ("manifest-payload", "manifest-digest"))
def test_objective_manifest_digest_mutation_fails_closed(tmp_path: Path, mutation: str) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    run_delta_minimize(config, backends=fixture.backends())
    if mutation == "manifest-payload":
        path = config.out_dir / "objective-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["target_spec"]["provenance"]["tampered"] = True
        path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        path = config.out_dir / "objective-inputs.json"
        inputs = json.loads(path.read_text(encoding="utf-8"))
        inputs["objective_manifest_digest"] = "0" * 64
        path.write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^corrupt-objective-cache-context$"):
        run_delta_minimize(config, backends=fixture.backends())


def test_validated_cached_objective_manifest_is_deeply_immutable() -> None:
    objective = run_module._objective_from_dict(_objective().to_dict(), function="f")

    with pytest.raises(TypeError):
        objective.target_spec["provenance"]["mutated"] = True
    with pytest.raises(TypeError):
        objective.desired_phys[1] = 4
    with pytest.raises(TypeError):
        objective.references["opcode"] = objective.references["color"]


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


def test_missing_target_function_stops_exact_publication(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    base = fixture.backends()

    def score_rows(rows, config):
        scored = base.evaluation.score_rows(rows, config)
        if rows[0]["candidate_id"] == "mask-10":
            scored[0].update(
                {
                    "error": "function 'f' not in compiled pcdump",
                    "score_error_kind": "candidate",
                    "terminal_safe": True,
                }
            )
        return scored

    backends = replace(
        base,
        evaluation=replace(base.evaluation, score_rows=score_rows),
    )
    result = run_delta_minimize(_config(tmp_path), backends=backends)

    assert result.status == "incomplete"
    assert result.candidate_counts["legal"] == 4
    assert result.pareto is None
    assert "candidate-target-function-missing" in result.blockers


def test_inspector_compile_error_stops_publication_and_retries(tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    config = _config(tmp_path)
    base = fixture.backends()
    calls = 0

    def inspect_source(_source, _function, output, **_kwargs):
        nonlocal calls
        calls += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "### mwcceppc.exe Compiler:\n# Error: broken\nCompilation finished.\n",
            encoding="utf-8",
        )
        raise DeltaMinimizeError("inspector-failed")

    backends = replace(
        base,
        evaluation=replace(base.evaluation, inspect_source=inspect_source),
    )
    for attempt in range(2):
        result = run_delta_minimize(config, backends=backends)
        assert result.status == "incomplete"
        assert result.pareto is None
        assert "inspector-failed" in result.blockers
        assert calls == attempt + 1


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
