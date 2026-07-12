from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import src.search.cli as search_cli
import src.search.delta_minimize.evaluator as evaluator_module
import src.search.delta_minimize.objectives as objectives_module
from src.mwcc_debug.colorgraph_profile import ColorGraphProfile
from src.mwcc_debug.objobject_profile import ObjObjectProfile
from src.mwcc_debug.role_descriptor import Compile, build_descriptors
from src.mwcc_debug.stack_home_profile import StackHomeProfile
from src.search.cli import search_app
from src.search.delta_minimize.epochs import PARSER_SCHEMA_HASH
from src.search.delta_minimize.evaluator import RawCandidateEvidence
from src.search.delta_minimize.objectives import ParentObjectiveEvidence, infer_objective_manifest
from src.search.delta_minimize.run import DeltaMinimizeBackends, run_delta_minimize
from tests.search.delta_minimize.test_run import _CountingFixture

FIXTURES = Path(__file__).parents[2] / "fixtures" / "delta_minimize"
ROLE_FIXTURE = Path(__file__).parents[2] / "fixtures" / "role_identity" / "mnVibration_matched_pcdump.txt"


class _ReviewedRoleFixture(_CountingFixture):
    def __init__(self, tmp_path: Path, left_source: str, right_source: str) -> None:
        super().__init__(tmp_path)
        self.left_source = left_source
        self.right_source = right_source
        self.dump_text = ROLE_FIXTURE.read_text(encoding="utf-8").replace(
            "mnVibration_80248644",
            "f",
        )
        self.left_dump = tmp_path / "left.pcdump"
        self.right_dump = tmp_path / "right.pcdump"
        self.left_dump.write_text(self.dump_text, encoding="utf-8")
        self.right_dump.write_text(f"{self.dump_text}\n", encoding="utf-8")

    def parent_provenance(self, config):
        return {
            **super().parent_provenance(config),
            "cflags_hash": "c" * 64,
            "expected_object_hash": "e" * 64,
            "parser_schema_hash": PARSER_SCHEMA_HASH,
        }

    def _raw(self, candidate, dump: Path) -> RawCandidateEvidence:
        return RawCandidateEvidence(
            candidate_id=candidate.candidate_id,
            mask=candidate.mask,
            source_path=str(candidate.source_path),
            source_hash=candidate.source_hash,
            compile_status="compiled",
            viable=True,
            pcdump_path=str(dump),
            checkdiff_evidence={
                "match": False,
                "target_asm": ["+000: 38 60 00 00 li r3,0"],
                "current_asm": ["+000: 38 80 00 00 li r4,0"],
                "classification": {"primary": "instruction-identical"},
            },
            inspect_text="FUNCTION: f\nFrontend: OBJOBJECTS\n",
            compiler_stderr="",
            pcdump_hash=hashlib.sha256(dump.read_bytes()).hexdigest(),
        )

    def capture_parent(self, candidate, _config, _store):
        self.parent_calls += 1
        dump = self.left_dump if candidate.candidate_id == "parent-left" else self.right_dump
        return self._raw(candidate, dump)

    def parent_objective(self, raw, side, _config):
        self.parent_objective_calls += 1
        assert raw.pcdump_path is not None
        source = Path(raw.source_path).read_text(encoding="utf-8")
        compile = Compile.from_text(Path(raw.pcdump_path).read_text(encoding="utf-8"), "f", source)
        return ParentObjectiveEvidence(
            side=side,
            function="f",
            class_id=0,
            compile=compile,
            pcdump_path=Path(raw.pcdump_path),
            expected_assembly=("+000: 38 60 00 00 li r3,0",),
            current_assembly=("+000: 38 80 00 00 li r4,0",),
            opcode_distance=(1, 0),
            color_profile=None,
            objobject_profile=ObjObjectProfile((), True),
            stack_home_profile=StackHomeProfile(32, (), True),
            stack_absolute_distance=(0, 0, 0, 0),
            stack_unresolved=(),
            expected_assembly_artifact="expected.o:f",
            pcdump_artifact=str(raw.pcdump_path),
            objobject_artifact=f"{side}.inspect.txt",
            stack_absolute_artifact="expected.o:f:stack",
            stack_profile_artifact=f"{side}.stack.json",
        )

    def infer_objective(self, left, right, config, *, namespace_resolution=None):
        self.infer_calls += 1
        return infer_objective_manifest(
            left,
            right,
            target_path=config.target_path,
            donor_overrides=config.donor_overrides,
            namespace_resolution=namespace_resolution,
        )

    def score_rows(self, rows, _score_config):
        self.score_calls += 1
        row = rows[0]
        mask = int(row["candidate_id"].split("-")[1], 2)
        source = Path(row["source_file"])
        self.captured_sources[mask] = source.read_bytes()
        dump = self.tmp_path / f"candidate-{mask}.pcdump"
        dump.write_text(self.dump_text + "\n" * (mask + 2), encoding="utf-8")
        return [
            {
                **row,
                "pcdump_path": str(dump),
                "score_returncode": 0,
                "score_error_kind": None,
                "score_stderr": "",
                "checkdiff_evidence": {
                    "match": False,
                    "target_asm": ["+000: 38 60 00 00 li r3,0"],
                    "current_asm": ["+000: 38 80 00 00 li r4,0"],
                    "classification": {"primary": "instruction-identical"},
                },
            }
        ]

    def backends(self) -> DeltaMinimizeBackends:
        return replace(
            super().backends(),
            profile_candidate=evaluator_module.profile_candidate,
        )


def _write_target(
    path: Path,
    fixture: _ReviewedRoleFixture,
    desired: dict[int, int],
    *,
    version: int,
) -> None:
    baseline_dump = fixture.left_dump
    if version == 2:
        baseline_dump = path.parent / "reviewed-baseline.pcdump"
        baseline_dump.write_bytes(fixture.left_dump.read_bytes())
    data: dict[str, object] = {
        "schema_version": f"delta-minimize-color-target.v{version}",
        "function": "f",
        "class_id": 0,
        "baseline_dump": str(baseline_dump),
        "force_phys": desired,
        "coalesce_preservation": False,
    }
    if version == 2:
        data.update(
            {
                "baseline_side": "left",
                "parent_role_bindings": {
                    side: {
                        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        "pcdump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                        "canonical_to_parent": {role: role for role in desired},
                    }
                    for side, source, dump in (
                        ("left", fixture.left_source, fixture.left_dump),
                        ("right", fixture.right_source, fixture.right_dump),
                    )
                },
            }
        )
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_wrapper_direct_fixture_has_exact_reproducible_frontier(monkeypatch, tmp_path: Path) -> None:
    fixture = _CountingFixture(tmp_path)
    left = FIXTURES / "left.c"
    right = FIXTURES / "right.c"
    out_dir = tmp_path / "run"
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: FIXTURES)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: left,
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda config: run_delta_minimize(config, backends=fixture.backends()),
    )
    argv = [
        "delta-minimize",
        "--function",
        "f",
        "--left",
        str(left),
        "--right",
        str(right),
        "--out-dir",
        str(out_dir),
        "--json",
    ]

    first = CliRunner().invoke(search_app, argv)
    second = CliRunner().invoke(search_app, argv)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert second.stdout == first.stdout
    result = json.loads(first.stdout)
    assert result["status"] in {"matched", "joint-zero", "frontier"}
    assert result["exact_four_axis"] is True
    assert result["candidate_counts"] == {"complete": 4, "legal": 4, "viable": 4}
    assert result["pareto"]["candidate_ids"]
    assert all(group["minimal_from_left"] for group in result["pareto"]["groups"])
    assert all(group["minimal_from_right"] for group in result["pareto"]["groups"])
    assert fixture.score_calls == 4
    assert (out_dir / "result.json").is_file()


def test_reviewed_v2_roles_publish_complete_reproducible_frontier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    left = FIXTURES / "left.c"
    right = FIXTURES / "right.c"
    left_source = left.read_text(encoding="utf-8")
    right_source = right.read_text(encoding="utf-8")
    fixture = _ReviewedRoleFixture(tmp_path, left_source, right_source)
    template = Compile.from_text(fixture.dump_text, "f", left_source)
    original = build_descriptors(template, 0)
    namespace_size = template.fev.coalesce_sections[-1].n_virtuals
    roles = list(original)
    assert len(roles) >= 4
    canonical = roles[:2]
    aliases = roles[2:4]
    desired = {canonical[0]: 30, canonical[1]: 29}
    unique = {
        ig_idx: replace(descriptor, first_def_sig=f"fixture-role:{ig_idx}")
        for ig_idx, descriptor in original.items()
    }
    duplicated = dict(unique)
    for canonical_ig, alias_ig in zip(canonical, aliases, strict=True):
        duplicated[alias_ig] = replace(unique[canonical_ig], ig_idx=alias_ig)

    def fixture_descriptors(compile: Compile, class_id: int):
        del compile
        assert class_id == 0
        return duplicated

    def fixture_color_profile(
        pcdump: str,
        function: str,
        class_id: int,
        role_map: dict[int, int],
        *,
        required_roles: frozenset[int],
    ) -> ColorGraphProfile:
        del pcdump, function, class_id
        stable_roles = tuple(sorted(set(role_map.values())))
        return ColorGraphProfile(
            assignments=tuple((role, desired.get(role, 0)) for role in stable_roles),
            simplify_order=stable_roles,
            select_order=stable_roles,
            interference_edges=frozenset(),
            coalesce_pairs=frozenset(),
            spills=frozenset(),
            complete=(
                required_roles <= set(stable_roles)
                and set(role_map) >= set(range(namespace_size))
            ),
        )

    monkeypatch.setattr(objectives_module.role_descriptor, "build_descriptors", fixture_descriptors)
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_virtual_semantic_identities",
        lambda _compile, class_id, virtual_count: (
            {ig_idx: (f"fixture-virtual:{ig_idx}", (), False, None) for ig_idx in range(virtual_count)}
            if class_id == 0
            else None
        ),
    )
    monkeypatch.setattr(objectives_module, "build_colorgraph_profile", fixture_color_profile)
    monkeypatch.setattr(evaluator_module, "build_colorgraph_profile", fixture_color_profile)
    monkeypatch.setattr(evaluator_module, "_stack_axis", lambda *_args: (0, 0, 0, 0))
    monkeypatch.setattr(evaluator_module, "_objobject_axis", lambda *_args: (0, 0))
    monkeypatch.setattr(search_cli, "_compute_melee_root", lambda: FIXTURES)
    monkeypatch.setattr(
        search_cli,
        "_resolve_structure_source_file",
        lambda function, source_file, *, melee_root: left,
    )
    monkeypatch.setattr(
        search_cli,
        "run_delta_minimize",
        lambda config: run_delta_minimize(config, backends=fixture.backends()),
    )
    v1_target = tmp_path / "target-v1.yaml"
    v2_target = tmp_path / "target-v2.yaml"
    _write_target(v1_target, fixture, desired, version=1)
    _write_target(v2_target, fixture, desired, version=2)

    common = [
        "delta-minimize",
        "--function",
        "f",
        "--left",
        str(left),
        "--right",
        str(right),
        "--donor",
        "color=left",
        "--donor",
        "objobjects=left",
        "--donor",
        "stack-homes=left",
        "--json",
    ]
    v1 = CliRunner().invoke(
        search_app,
        [*common, "--target", str(v1_target), "--out-dir", str(tmp_path / "v1")],
    )
    assert v1.exit_code == 2
    assert "ambiguous-color-target" in v1.output

    argv = [*common, "--target", str(v2_target), "--out-dir", str(tmp_path / "v2")]
    first = CliRunner().invoke(search_app, argv)
    second = CliRunner().invoke(search_app, argv)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert second.stdout == first.stdout
    result = json.loads(first.stdout)
    expected_candidate_ids = ["mask-00", "mask-01", "mask-10", "mask-11"]
    assert result["status"] in {"matched", "joint-zero", "frontier"}
    assert result["exact_four_axis"] is True
    assert result["candidate_counts"] == {"complete": 4, "legal": 4, "viable": 4}
    assert [candidate["candidate_id"] for candidate in result["candidates"]] == (
        expected_candidate_ids
    )
    assert all(
        candidate["profile"]["complete"]
        for candidate in result["candidates"]
        if candidate["profile"]["viable"]
    )
    assert result["pareto"]["candidate_ids"] == expected_candidate_ids
    namespace = result["objective_manifest"]["namespace_resolution"]
    resolution = json.loads(
        (tmp_path / "v2" / namespace["resolution_artifact"]).read_text(
            encoding="utf-8"
        )
    )
    assert resolution["request"]["reviewed_anchors"] == {
        str(role): role for role in desired
    }
    assert all(
        row["source"] in {"inheritance", "automatic-v5"}
        for row in resolution["resolutions"].values()
    )
    assert json.loads(second.stdout) == result
    assert json.loads((tmp_path / "v2" / "result.json").read_text()) == result
    assert fixture.captured_sources[0] == left.read_bytes()
    assert fixture.captured_sources[3] == right.read_bytes()
