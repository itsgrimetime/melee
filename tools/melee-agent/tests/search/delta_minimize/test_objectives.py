from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.mwcc_debug.colorgraph_profile import ColorGraphProfile
from src.mwcc_debug.objobject_profile import ObjObjectIdentity, ObjObjectProfile
from src.mwcc_debug.role_descriptor import Compile, build_descriptors
from src.mwcc_debug.stack_home_profile import StackHome, StackHomeProfile
from src.search.delta_minimize import DeltaMinimizeError
from src.search.delta_minimize.objectives import (
    ParentObjectiveEvidence,
    infer_objective_manifest,
    load_color_target,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "role_identity"
FUNCTION = "mnVibration_80248644"


@pytest.fixture(scope="module")
def baseline_compile() -> Compile:
    dump = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    return Compile.from_text(dump, FUNCTION, "")


@pytest.fixture(scope="module")
def desired_phys(baseline_compile: Compile) -> dict[int, int]:
    roles = [ig for ig, descriptor in build_descriptors(baseline_compile, 0).items() if descriptor.first_def_sig][:2]
    assert len(roles) == 2
    return {roles[0]: 22, roles[1]: 21}


def _write_target(
    root: Path,
    baseline: Path,
    desired: dict[int, int],
    **changes: object,
) -> Path:
    data: dict[str, object] = {
        "schema_version": "delta-minimize-color-target.v1",
        "function": FUNCTION,
        "class_id": 0,
        "baseline_dump": baseline.name,
        "force_phys": desired,
        "coalesce_preservation": True,
    }
    data.update(changes)
    path = root / "target.yaml"
    lines = [
        f"schema_version: {data['schema_version']}",
        f"function: {data['function']}",
        f"class_id: {data['class_id']}",
        f"baseline_dump: {data['baseline_dump']}",
        "force_phys:",
    ]
    lines.extend(f"  {ig}: {physical}" for ig, physical in data["force_phys"].items())
    lines.append(f"coalesce_preservation: {str(data['coalesce_preservation']).lower()}")
    known = {
        "schema_version",
        "function",
        "class_id",
        "baseline_dump",
        "force_phys",
        "coalesce_preservation",
    }
    lines.extend(f"{key}: {value}" for key, value in data.items() if key not in known)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _color_profile(
    desired: dict[int, int],
    *,
    reverse_secondary: bool = False,
    miss: int = 0,
) -> ColorGraphProfile:
    roles = tuple(desired)
    secondary = tuple(reversed(roles)) if reverse_secondary else roles
    assignments = tuple(
        (role, physical + (miss if index == 0 else 0)) for index, (role, physical) in enumerate(desired.items())
    )
    return ColorGraphProfile(
        assignments=assignments,
        simplify_order=secondary,
        select_order=secondary,
        interference_edges=frozenset({tuple(sorted(roles))}) if len(roles) == 2 else frozenset(),
        coalesce_pairs=frozenset(),
        spills=frozenset(),
        complete=True,
    )


def _obj_profile(name: str) -> ObjObjectProfile:
    identity = ObjObjectIdentity("local", name, "int", FUNCTION, name)
    return ObjObjectProfile((identity,), True)


def _stack_profile(identity: str = "symbol:x") -> StackHomeProfile:
    return StackHomeProfile(32, (StackHome(identity, 8, 0, "absolute"),), True)


def _parent(
    side: str,
    compile: Compile,
    dump: Path,
    desired: dict[int, int],
    *,
    color_profile: ColorGraphProfile | None = None,
    opcode_distance: tuple[int, int] = (1, 0),
    stack_distance: tuple[int, int, int, int] = (0, 0, 0, 0),
    stack_unresolved: tuple[str, ...] = (),
) -> ParentObjectiveEvidence:
    return ParentObjectiveEvidence(
        side=side,
        function=FUNCTION,
        class_id=0,
        compile=compile,
        pcdump_path=dump,
        expected_assembly=("+000: 38 60 00 00 li r3,0",),
        current_assembly=("+000: 38 80 00 00 li r4,0",),
        opcode_distance=opcode_distance,
        color_profile=color_profile or _color_profile(desired),
        objobject_profile=_obj_profile(side),
        stack_home_profile=_stack_profile(),
        stack_absolute_distance=stack_distance,
        stack_unresolved=stack_unresolved,
        expected_assembly_artifact="expected.o:draw",
        pcdump_artifact=f"{side}.pcdump",
        objobject_artifact=f"{side}.inspect.txt",
        stack_absolute_artifact="expected.o:frame",
        stack_profile_artifact=f"{side}.stack.json",
    )


def _derivation_payload(force_phys: dict[int, int]) -> dict[str, object]:
    targets = [
        {
            "class_id": 0,
            "kind": "r",
            "ig_idx": ig_idx,
            "target_reg": physical,
            "confidence": "exact",
            "force_vector_runnable": True,
        }
        for ig_idx, physical in force_phys.items()
    ]
    return {
        "force_phys": {str(ig_idx): physical for ig_idx, physical in force_phys.items()},
        "targets": targets,
        "conflicts": [],
        "actionability": {
            "status": "needs-move" if targets else "no-runnable-targets",
            "target_count": len(targets),
            "runnable_target_count": len(targets),
        },
        "force_vector_recommended": bool(targets),
    }


def _explicit_inputs(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    *,
    left_color: ColorGraphProfile | None = None,
    right_color: ColorGraphProfile | None = None,
    left_stack_distance: tuple[int, int, int, int] = (0, 0, 0, 0),
    right_stack_distance: tuple[int, int, int, int] = (0, 0, 0, 0),
    unresolved: tuple[str, ...] = (),
) -> tuple[ParentObjectiveEvidence, ParentObjectiveEvidence, Path]:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text(
        (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    target = _write_target(tmp_path, dump, desired_phys)
    left = _parent(
        "left",
        baseline_compile,
        dump,
        desired_phys,
        color_profile=left_color,
        stack_distance=left_stack_distance,
        stack_unresolved=unresolved,
    )
    right = _parent(
        "right",
        baseline_compile,
        dump,
        desired_phys,
        color_profile=right_color,
        stack_distance=right_stack_distance,
        stack_unresolved=unresolved,
    )
    return left, right, target


def test_color_target_v1_validates_function_and_baseline(
    tmp_path: Path,
    desired_phys: dict[int, int],
) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_text("dump", encoding="utf-8")
    path = _write_target(tmp_path, baseline, desired_phys)

    target = load_color_target(path, function=FUNCTION)

    assert dict(target.force_phys) == desired_phys
    assert target.baseline_dump == baseline.resolve()
    assert target.coalesce_preservation is True


@pytest.mark.parametrize(
    ("yaml_text", "reason"),
    [
        (
            "schema_version: delta-minimize-color-target.v1\n"
            f"function: {FUNCTION}\nclass_id: 0\nbaseline_dump: baseline.pcdump\n"
            "force_phys: {66: 22}\ncoalesce_preservation: true\nunknown: value\n",
            "invalid-color-target-fields",
        ),
        (
            "schema_version: delta-minimize-color-target.v1\n"
            f"function: {FUNCTION}\nclass_id: true\nbaseline_dump: baseline.pcdump\n"
            "force_phys: {66: 22}\ncoalesce_preservation: true\n",
            "invalid-color-target-class",
        ),
        (
            "schema_version: delta-minimize-color-target.v1\n"
            f"function: {FUNCTION}\nclass_id: 0\nbaseline_dump: baseline.pcdump\n"
            "force_phys: {true: 22}\ncoalesce_preservation: true\n",
            "invalid-color-target-force-phys",
        ),
        (
            "schema_version: delta-minimize-color-target.v1\n"
            f"function: {FUNCTION}\nclass_id: 0\nbaseline_dump: baseline.pcdump\n"
            "force_phys: {66: 32}\ncoalesce_preservation: true\n",
            "invalid-color-target-force-phys",
        ),
        (
            "schema_version: delta-minimize-color-target.v1\n"
            f"function: {FUNCTION}\nclass_id: 0\nbaseline_dump: baseline.pcdump\n"
            "force_phys: {66: 22}\ncoalesce_preservation: 1\n",
            "invalid-color-target-coalesce-policy",
        ),
    ],
)
def test_color_target_rejects_unknown_and_ambiguously_typed_fields(
    tmp_path: Path,
    yaml_text: str,
    reason: str,
) -> None:
    (tmp_path / "baseline.pcdump").write_text("dump", encoding="utf-8")
    path = tmp_path / "target.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(DeltaMinimizeError, match=reason):
        load_color_target(path, function=FUNCTION)


def test_color_target_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    (tmp_path / "baseline.pcdump").write_text("dump", encoding="utf-8")
    path = tmp_path / "target.yaml"
    path.write_text(
        "schema_version: delta-minimize-color-target.v1\n"
        f"function: {FUNCTION}\nfunction: other\n"
        "class_id: 0\nbaseline_dump: baseline.pcdump\n"
        "force_phys: {66: 22}\ncoalesce_preservation: true\n",
        encoding="utf-8",
    )
    with pytest.raises(DeltaMinimizeError, match="ambiguous-color-target-yaml"):
        load_color_target(path, function=FUNCTION)


def test_color_target_rejects_relative_path_escape(tmp_path: Path, desired_phys: dict[int, int]) -> None:
    outside = tmp_path.parent / "outside.pcdump"
    outside.write_text("dump", encoding="utf-8")
    path = _write_target(tmp_path, outside, desired_phys, baseline_dump="../outside.pcdump")
    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-baseline"):
        load_color_target(path, function=FUNCTION)


def test_color_target_rejects_symlink_even_when_target_stays_inside_root(
    tmp_path: Path,
    desired_phys: dict[int, int],
) -> None:
    real = tmp_path / "real.pcdump"
    real.write_text("dump", encoding="utf-8")
    link = tmp_path / "linked.pcdump"
    link.symlink_to(real)
    path = _write_target(tmp_path, link, desired_phys)
    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-baseline"):
        load_color_target(path, function=FUNCTION)


def test_color_target_rejects_intermediate_symlink_component(
    tmp_path: Path,
    desired_phys: dict[int, int],
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "baseline.pcdump").write_text("dump", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    path = _write_target(
        tmp_path,
        real / "baseline.pcdump",
        desired_phys,
        baseline_dump="linked/baseline.pcdump",
    )
    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-baseline"):
        load_color_target(path, function=FUNCTION)


def test_color_target_rejects_target_file_beneath_symlinked_directory(
    tmp_path: Path,
    desired_phys: dict[int, int],
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    baseline = real / "baseline.pcdump"
    baseline.write_text("dump", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    path = _write_target(linked, baseline, desired_phys)
    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-file"):
        load_color_target(path, function=FUNCTION)


def test_explicit_target_requires_round_trip_stable_roles(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    target.write_text(target.read_text().replace(next(map(str, desired_phys)), "999999"), encoding="utf-8")
    with pytest.raises(DeltaMinimizeError, match="ambiguous-color-target"):
        infer_objective_manifest(
            left,
            right,
            target_path=target,
            donor_overrides={"color": "left", "objobjects": "left"},
        )


def test_injected_baseline_compile_failure_fails_closed(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    external_dump = tmp_path / "external.pcdump"
    external_dump.write_text(left.pcdump_path.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text(
        target.read_text(encoding="utf-8").replace("baseline.pcdump", "external.pcdump"),
        encoding="utf-8",
    )
    left = replace(left, pcdump_path=tmp_path / "left.pcdump")
    right = replace(right, pcdump_path=tmp_path / "right.pcdump")
    left.pcdump_path.write_text("left", encoding="utf-8")
    right.pcdump_path.write_text("right", encoding="utf-8")

    def broken_loader(path: Path, function: str, source: str) -> Compile:
        del path, function, source
        raise RuntimeError("compiler unavailable")

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=target,
            donor_overrides={},
            compile_loader=broken_loader,
        )


def test_conflicting_parent_role_targets_require_explicit_target(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left = _parent("left", baseline_compile, dump, desired_phys)
    right = _parent("right", baseline_compile, dump, desired_phys)
    calls: list[str] = []

    def derive(target_asm, current_asm, pre_pass, events):
        del target_asm, current_asm, pre_pass, events
        side = ("left", "right")[len(calls)]
        calls.append(side)
        result = dict(desired_phys)
        if side == "right":
            first = next(iter(result))
            result[first] += 1
        return _derivation_payload(result)

    with pytest.raises(DeltaMinimizeError, match="ambiguous-color-target"):
        infer_objective_manifest(
            left,
            right,
            target_path=None,
            donor_overrides={},
            derive_force_target=derive,
        )
    assert calls == ["left", "right"]


def test_missing_derived_parent_target_is_reported_as_ambiguous(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left = _parent("left", baseline_compile, dump, desired_phys)
    right = _parent("right", baseline_compile, dump, desired_phys)
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=None,
            donor_overrides={},
            derive_force_target=lambda *_: _derivation_payload({}),
        )


def test_derived_parent_conflicts_are_ambiguous_even_with_runnable_map(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left = _parent("left", baseline_compile, dump, desired_phys)
    right = _parent("right", baseline_compile, dump, desired_phys)
    payload = _derivation_payload(desired_phys)
    payload["conflicts"] = [{"ig_idx": next(iter(desired_phys))}]
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=None,
            donor_overrides={},
            derive_force_target=lambda *_: payload,
        )


def test_equal_assignment_distance_with_different_graphs_requires_color_donor(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(
        tmp_path,
        baseline_compile,
        desired_phys,
        left_color=_color_profile(desired_phys),
        right_color=_color_profile(desired_phys, reverse_secondary=True),
    )
    with pytest.raises(DeltaMinimizeError, match="ambiguous-color-donor"):
        infer_objective_manifest(left, right, target_path=target, donor_overrides={})


def test_identical_tied_secondary_profiles_may_leave_color_without_donor(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    manifest = infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"objobjects": "right"},
    )
    assert manifest.color_donor is None
    assert manifest.objobject_donor == "right"
    assert manifest.references["color"].donor is None
    assert "left.pcdump" in manifest.references["color"].reference_artifact
    assert "right.pcdump" in manifest.references["color"].reference_artifact


def test_objobjects_default_to_selected_color_donor(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(
        tmp_path,
        baseline_compile,
        desired_phys,
        left_color=_color_profile(desired_phys),
        right_color=_color_profile(desired_phys, miss=1),
    )
    manifest = infer_objective_manifest(left, right, target_path=target, donor_overrides={})
    assert manifest.color_donor == "left"
    assert manifest.objobject_donor == "left"
    assert manifest.references["objobjects"].reference_kind == "proxy"


def test_unresolved_stack_proxy_requires_strictly_better_donor(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(
        tmp_path,
        baseline_compile,
        desired_phys,
        left_stack_distance=(1, 4, 0, 0),
        right_stack_distance=(2, 8, 0, 0),
        unresolved=("compiler-temp:row-child",),
    )
    manifest = infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"objobjects": "left"},
    )
    assert manifest.stack_home_donor == "left"
    assert manifest.references["stack-homes"].reference_kind == "mixed"
    assert manifest.references["stack-homes"].unresolved == ("compiler-temp:row-child",)
    assert manifest.references["stack-homes"].reference_artifact == (
        "absolute=expected.o:frame;secondary=left.stack.json"
    )


def test_tied_unresolved_stack_proxy_fails_closed(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(
        tmp_path,
        baseline_compile,
        desired_phys,
        left_stack_distance=(1, 4, 0, 0),
        right_stack_distance=(1, 4, 0, 0),
        unresolved=("compiler-temp:row-child",),
    )
    with pytest.raises(DeltaMinimizeError, match="ambiguous-stack-home-donor"):
        infer_objective_manifest(
            left,
            right,
            target_path=target,
            donor_overrides={"objobjects": "left"},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"opcode": "left"},
        {"color": "middle"},
        {"stack_homes": "left"},
        {"color": True},
    ],
)
def test_donor_override_axes_and_values_are_strictly_validated(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    overrides: dict[str, object],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    with pytest.raises(DeltaMinimizeError, match="invalid-donor-override"):
        infer_objective_manifest(left, right, target_path=target, donor_overrides=overrides)


def test_invalid_parent_path_type_fails_closed(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    malformed = replace(left, pcdump_path="baseline.pcdump")
    with pytest.raises(DeltaMinimizeError, match="invalid-parent-evidence"):
        infer_objective_manifest(malformed, right, target_path=target, donor_overrides={})


@pytest.mark.parametrize(
    "changes",
    [
        {"class_id": True},
        {"objobject_profile": object()},
        {"stack_home_profile": object()},
        {"color_profile": object()},
        {"expected_assembly": ["line"]},
    ],
)
def test_malformed_parent_types_fail_closed(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    changes: dict[str, object],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    malformed = replace(left, **changes)
    with pytest.raises(DeltaMinimizeError, match="invalid-parent-evidence"):
        infer_objective_manifest(malformed, right, target_path=target, donor_overrides={})


def test_manifest_serialization_is_deterministic_and_json_friendly(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    manifest = infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"color": "right", "objobjects": "left"},
    )
    first = manifest.to_json()
    assert first == manifest.to_json()
    payload = json.loads(first)
    assert payload["schema_version"] == "delta-minimize-objectives.v1"
    assert payload["references"]["opcode"]["reference_artifact"] == "expected.o:draw"
    assert payload["references"]["opcode"]["reference_kind"] == "absolute"
    assert payload["references"]["color"]["override"] is True
    assert payload["desired_phys"] == {str(key): value for key, value in desired_phys.items()}
    with pytest.raises(TypeError):
        manifest.target_spec["provenance"]["mutated"] = True
