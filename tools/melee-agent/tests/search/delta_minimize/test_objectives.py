from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

import src.search.delta_minimize.objectives as objectives_module
from src.mwcc_debug import role_descriptor
from src.mwcc_debug.colorgraph_profile import ColorGraphProfile
from src.mwcc_debug.objobject_profile import ObjObjectIdentity, ObjObjectProfile
from src.mwcc_debug.role_descriptor import Compile, build_descriptors
from src.mwcc_debug.stack_home_profile import StackHome, StackHomeProfile
from src.search.delta_minimize import DeltaMinimizeError
from src.search.delta_minimize.objectives import (
    ParentObjectiveEvidence,
    ParentRoleBinding,
    infer_objective_manifest,
    load_color_target,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "role_identity"
FUNCTION = "mnVibration_80248644"


def _complete_semantic_identities(
    _compile: Compile,
    class_id: int,
    virtual_count: int,
) -> dict[int, tuple] | None:
    if class_id != 0:
        return None
    return {
        ig_idx: (f"fixture-virtual:{ig_idx}", (), False, None)
        for ig_idx in range(virtual_count)
    }


@pytest.fixture(scope="module")
def baseline_compile() -> Compile:
    dump = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    return Compile.from_text(dump, FUNCTION, "")


@pytest.fixture(scope="module")
def desired_phys(baseline_compile: Compile) -> dict[int, int]:
    roles = [ig for ig, descriptor in build_descriptors(baseline_compile, 0).items() if descriptor.first_def_sig][:2]
    assert len(roles) == 2
    return {roles[0]: 22, roles[1]: 21}


def test_explicit_baseline_self_check_uses_exact_ig_identity(
    monkeypatch, baseline_compile: Compile, desired_phys: dict[int, int]
) -> None:
    target = role_descriptor.build_target_spec(
        baseline_compile,
        desired_phys,
        0,
        "force_proof_proxy",
        {"schema_version": "delta-minimize-color-target.v1"},
    )
    monkeypatch.setattr(
        objectives_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("self-check should not descriptor-reanchor")),
    )

    result = objectives_module._require_complete_reanchor(
        target,
        baseline_compile,
        0,
        desired_phys,
        exact_identity=True,
    )

    assert result.force_phys == desired_phys
    assert result.matched == {ig: ig for ig in desired_phys}


def test_exact_ig_identity_rejects_changed_semantic_role(
    monkeypatch: pytest.MonkeyPatch,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    target = role_descriptor.build_target_spec(
        baseline_compile,
        desired_phys,
        0,
        "force_proof_proxy",
        {"inference": "parent-register-diff"},
    )
    descriptors = build_descriptors(baseline_compile, 0)
    changed_ig = next(iter(desired_phys))
    changed = {
        **descriptors,
        changed_ig: replace(
            descriptors[changed_ig],
            first_def_sig=f"changed:{descriptors[changed_ig].first_def_sig}",
        ),
    }
    monkeypatch.setattr(objectives_module.role_descriptor, "build_descriptors", lambda *_args: changed)

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        objectives_module._require_complete_reanchor(
            target,
            baseline_compile,
            0,
            desired_phys,
            exact_identity=True,
        )


def test_allocator_namespace_witness_includes_semantic_role_identity(
    monkeypatch: pytest.MonkeyPatch,
    baseline_compile: Compile,
) -> None:
    identities = _complete_semantic_identities(
        baseline_compile,
        0,
        baseline_compile.fev.coalesce_sections[-1].n_virtuals,
    )
    assert identities is not None
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_virtual_semantic_identities",
        lambda *_args: identities,
    )
    original = objectives_module._allocator_namespace_witness(baseline_compile, 0)
    assert original is not None
    changed_ig = next(iter(identities))
    changed = {
        **identities,
        changed_ig: ("semantically-different", (), False, None),
    }
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_virtual_semantic_identities",
        lambda *_args: changed,
    )

    assert objectives_module._allocator_namespace_witness(baseline_compile, 0) != original


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


def _v2_target_data(baseline: Path, desired: dict[int, int]) -> dict[str, object]:
    dump_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    canonical = {str(ig_idx): ig_idx for ig_idx in desired}
    return {
        "schema_version": "delta-minimize-color-target.v2",
        "function": FUNCTION,
        "class_id": 0,
        "baseline_side": "left",
        "baseline_dump": baseline.name,
        "force_phys": {str(ig_idx): physical for ig_idx, physical in desired.items()},
        "coalesce_preservation": True,
        "parent_role_bindings": {
            "left": {
                "source_sha256": "1" * 64,
                "pcdump_sha256": dump_hash,
                "canonical_to_parent": canonical,
            },
            "right": {
                "source_sha256": "2" * 64,
                "pcdump_sha256": "3" * 64,
                "canonical_to_parent": canonical,
            },
        },
    }


def _write_v2_target(root: Path, baseline: Path, desired: dict[int, int]) -> Path:
    path = root / "target-v2.yaml"
    path.write_text(yaml.safe_dump(_v2_target_data(baseline, desired), sort_keys=False), encoding="utf-8")
    return path


def _write_bound_v2_target(
    root: Path,
    left: ParentObjectiveEvidence,
    right: ParentObjectiveEvidence,
    desired: dict[int, int],
    *,
    right_map: dict[int, int] | None = None,
) -> Path:
    data = _v2_target_data(left.pcdump_path, desired)
    bindings = data["parent_role_bindings"]
    assert isinstance(bindings, dict)
    for parent in (left, right):
        binding = bindings[parent.side]
        assert isinstance(binding, dict)
        binding["source_sha256"] = hashlib.sha256(parent.compile.source.encode("utf-8")).hexdigest()
        binding["pcdump_sha256"] = hashlib.sha256(parent.pcdump_path.read_bytes()).hexdigest()
    if right_map is not None:
        right_binding = bindings["right"]
        assert isinstance(right_binding, dict)
        right_binding["canonical_to_parent"] = {str(key): value for key, value in right_map.items()}
    path = root / "bound-v2.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
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


def _stack_profile(
    identity: str = "symbol:x",
    *,
    reference_kind: str = "absolute",
) -> StackHomeProfile:
    return StackHomeProfile(32, (StackHome(identity, 8, 0, reference_kind),), True)


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
    stack_profile: StackHomeProfile | None = None,
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
        stack_home_profile=stack_profile or _stack_profile(),
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
            "current_reg": physical + 1,
            "already_target": False,
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
            "already_target_count": 0,
            "needs_move_count": len(targets),
            "unknown_current_count": 0,
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
    stack_profile: StackHomeProfile | None = None,
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
        stack_profile=stack_profile,
    )
    right = _parent(
        "right",
        baseline_compile,
        dump,
        desired_phys,
        color_profile=right_color,
        stack_distance=right_stack_distance,
        stack_unresolved=unresolved,
        stack_profile=stack_profile,
    )
    return left, right, target


def _duplicate_role_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> tuple[
    ParentObjectiveEvidence,
    ParentObjectiveEvidence,
    role_descriptor.TargetSpec,
    dict[str, ParentRoleBinding],
    dict[int, int],
]:
    del desired_phys
    desired = {64: 30, 78: 29}
    canonical = tuple(desired)
    left_compile = baseline_compile
    right_compile = deepcopy(baseline_compile)
    fixture_descriptors = list(build_descriptors(baseline_compile, 0).values())[:2]
    assert len(fixture_descriptors) == 2
    baseline_descriptors = {
        canonical_ig: replace(descriptor, ig_idx=canonical_ig)
        for canonical_ig, descriptor in zip(canonical, fixture_descriptors, strict=True)
    }
    alias_base = 164
    aliases = {canonical[0]: alias_base, canonical[1]: alias_base + 1}
    right_descriptors = dict(baseline_descriptors)
    for canonical_ig, alias_ig in aliases.items():
        right_descriptors[alias_ig] = replace(
            baseline_descriptors[canonical_ig],
            ig_idx=alias_ig,
        )

    def duplicate_descriptors(compile: Compile, class_id: int):
        assert class_id == 0
        if compile is right_compile:
            return right_descriptors
        return baseline_descriptors

    monkeypatch.setattr(objectives_module.role_descriptor, "build_descriptors", duplicate_descriptors)
    dump_text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    left_dump = tmp_path / "left.pcdump"
    right_dump = tmp_path / "right.pcdump"
    left_dump.write_text(dump_text, encoding="utf-8")
    right_dump.write_text(dump_text, encoding="utf-8")
    left = _parent("left", left_compile, left_dump, desired)
    right = _parent("right", right_compile, right_dump, desired)
    target_spec = objectives_module._target_spec(
        left_compile,
        desired,
        0,
        {"schema_version": "delta-minimize-color-target.v2"},
        False,
    )
    bindings = {
        parent.side: ParentRoleBinding(
            source_sha256=hashlib.sha256(parent.compile.source.encode("utf-8")).hexdigest(),
            pcdump_sha256=hashlib.sha256(parent.pcdump_path.read_bytes()).hexdigest(),
            canonical_to_parent={ig_idx: ig_idx for ig_idx in canonical},
        )
        for parent in (left, right)
    }
    return left, right, target_spec, bindings, aliases


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


def test_color_target_v2_loads_reviewed_parent_role_bindings(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_bytes(b"reviewed baseline dump\n")
    target_path = _write_v2_target(tmp_path, baseline, {64: 30, 78: 29})

    loaded = load_color_target(target_path, function=FUNCTION)

    assert loaded.schema_version == "delta-minimize-color-target.v2"
    assert loaded.baseline_side == "left"
    assert dict(loaded.parent_role_bindings["right"].canonical_to_parent) == {64: 64, 78: 78}


@pytest.mark.parametrize(
    "malformation",
    [
        "missing-top-level-field",
        "extra-top-level-field",
        "missing-binding-field",
        "extra-binding-field",
        "missing-side",
        "uppercase-hash",
        "short-hash",
        "partial-canonical-map",
        "extra-canonical-key",
        "duplicate-parent-ig",
        "nonidentity-baseline",
    ],
)
def test_color_target_v2_rejects_malformed_parent_role_binding(
    tmp_path: Path,
    malformation: str,
) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_bytes(b"reviewed baseline dump\n")
    data = _v2_target_data(baseline, {64: 30, 78: 29})
    bindings = data["parent_role_bindings"]
    assert isinstance(bindings, dict)
    left = bindings["left"]
    right = bindings["right"]
    assert isinstance(left, dict)
    assert isinstance(right, dict)

    if malformation == "missing-top-level-field":
        del data["baseline_side"]
    elif malformation == "extra-top-level-field":
        data["unexpected"] = True
    elif malformation == "missing-binding-field":
        del right["source_sha256"]
    elif malformation == "extra-binding-field":
        right["unexpected"] = True
    elif malformation == "missing-side":
        del bindings["right"]
    elif malformation == "uppercase-hash":
        right["source_sha256"] = "A" * 64
    elif malformation == "short-hash":
        right["pcdump_sha256"] = "3" * 63
    elif malformation == "partial-canonical-map":
        right["canonical_to_parent"] = {"64": 64}
    elif malformation == "extra-canonical-key":
        right["canonical_to_parent"] = {"64": 64, "78": 78, "99": 99}
    elif malformation == "duplicate-parent-ig":
        right["canonical_to_parent"] = {"64": 64, "78": 64}
    else:
        left["canonical_to_parent"] = {"64": 78, "78": 64}

    target_path = tmp_path / "malformed-v2.yaml"
    target_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError):
        load_color_target(target_path, function=FUNCTION)


def test_color_target_v2_rejects_baseline_dump_hash_mismatch(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_bytes(b"reviewed baseline dump\n")
    data = _v2_target_data(baseline, {64: 30, 78: 29})
    bindings = data["parent_role_bindings"]
    assert isinstance(bindings, dict)
    left = bindings["left"]
    assert isinstance(left, dict)
    left["pcdump_sha256"] = "0" * 64
    target_path = tmp_path / "tampered-v2.yaml"
    target_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(DeltaMinimizeError):
        load_color_target(target_path, function=FUNCTION)


def test_color_target_v1_has_no_reviewed_parent_bindings(
    tmp_path: Path,
    desired_phys: dict[int, int],
) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_text("dump", encoding="utf-8")

    loaded = load_color_target(_write_target(tmp_path, baseline, desired_phys), function=FUNCTION)

    assert loaded.schema_version == "delta-minimize-color-target.v1"
    assert loaded.baseline_side is None
    assert dict(loaded.parent_role_bindings) == {}


def test_color_target_accepts_canonical_json_force_phys_keys(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_text("dump", encoding="utf-8")
    path = tmp_path / "target.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "delta-minimize-color-target.v1",
                "function": FUNCTION,
                "class_id": 0,
                "baseline_dump": baseline.name,
                "force_phys": {"0": 3, "66": 22},
                "coalesce_preservation": True,
            }
        ),
        encoding="utf-8",
    )

    target = load_color_target(path, function=FUNCTION)

    assert dict(target.force_phys) == {0: 3, 66: 22}


@pytest.mark.parametrize(
    "ig_key",
    ["", "-1", "+1", " 1", "1 ", "01", "00", "1.0", "1e2", "0x10", "true"],
)
def test_color_target_rejects_noncanonical_string_ig_keys(
    tmp_path: Path,
    ig_key: str,
) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_text("dump", encoding="utf-8")
    path = tmp_path / "target.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "delta-minimize-color-target.v1",
                "function": FUNCTION,
                "class_id": 0,
                "baseline_dump": baseline.name,
                "force_phys": {ig_key: 22},
                "coalesce_preservation": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-force-phys"):
        load_color_target(path, function=FUNCTION)


def test_color_target_rejects_ig_collision_after_key_normalization(tmp_path: Path) -> None:
    (tmp_path / "baseline.pcdump").write_text("dump", encoding="utf-8")
    path = tmp_path / "target.yaml"
    path.write_text(
        "schema_version: delta-minimize-color-target.v1\n"
        f"function: {FUNCTION}\nclass_id: 0\nbaseline_dump: baseline.pcdump\n"
        'force_phys: {66: 22, "66": 21}\ncoalesce_preservation: true\n',
        encoding="utf-8",
    )

    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-force-phys"):
        load_color_target(path, function=FUNCTION)


@pytest.mark.parametrize("physical", [True, False, -1, 32, "22", 22.0, None])
def test_color_target_rejects_invalid_json_physical_values(
    tmp_path: Path,
    physical: object,
) -> None:
    baseline = tmp_path / "baseline.pcdump"
    baseline.write_text("dump", encoding="utf-8")
    path = tmp_path / "target.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "delta-minimize-color-target.v1",
                "function": FUNCTION,
                "class_id": 0,
                "baseline_dump": baseline.name,
                "force_phys": {"66": physical},
                "coalesce_preservation": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeltaMinimizeError, match="invalid-color-target-force-phys"):
        load_color_target(path, function=FUNCTION)


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


def test_independent_parent_targets_use_cross_parent_semantic_reanchor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left = _parent("left", baseline_compile, dump, desired_phys)
    right_compile = deepcopy(baseline_compile)
    right = _parent("right", right_compile, dump, desired_phys)
    left_ig, right_ig = list(desired_phys)[:2]
    left_force = {left_ig: 22}
    right_force = {right_ig: 22}
    derivations = iter((_derivation_payload(left_force), _derivation_payload(right_force)))
    reanchors: list[str] = []

    def semantic_reanchor(target, compile, *, class_id):
        assert class_id == 0
        side = target.provenance["parent"]
        reanchors.append(side)
        if side == "left" and compile is right_compile:
            return objectives_module.role_reanchor.ReanchorResult(
                class_id=0,
                force_phys=right_force,
                diagnostics={},
                matched={right_ig: left_ig},
            )
        if side == "right" and compile is baseline_compile:
            return objectives_module.role_reanchor.ReanchorResult(
                class_id=0,
                force_phys=left_force,
                diagnostics={},
                matched={left_ig: right_ig},
            )
        raise AssertionError("unexpected semantic reanchor")

    monkeypatch.setattr(objectives_module.role_reanchor, "reanchor", semantic_reanchor)

    loaded, _target = objectives_module._derive_target_spec(
        left,
        right,
        lambda *_args: next(derivations),
    )

    assert dict(loaded.force_phys) == left_force
    assert reanchors == ["left", "right"]


def test_v2_reviewed_parent_bindings_resolve_duplicate_semantic_roles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target_spec, _bindings, _aliases = _duplicate_role_inputs(
        monkeypatch,
        tmp_path,
        baseline_compile,
        desired_phys,
    )
    desired = {role.original_ig: role.desired_phys for role in target_spec.roles}
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        objectives_module._require_complete_reanchor(target_spec, right.compile, 0, desired)

    target_path = _write_bound_v2_target(tmp_path, left, right, desired)
    monkeypatch.setattr(objectives_module, "_complete_profile_role_map", lambda *_args, **_kwargs: {})
    seen_role_maps: dict[str, dict[int, int]] = {}

    def capture_profile(parent, role_map, _desired):
        seen_role_maps[parent.side] = dict(role_map)
        assert parent.color_profile is not None
        return parent.color_profile

    monkeypatch.setattr(objectives_module, "_profile_for_parent", capture_profile)

    manifest = infer_objective_manifest(
        left,
        right,
        target_path=target_path,
        donor_overrides={"objobjects": "left"},
        compile_loader=lambda *_args: left.compile,
    )

    expected = {canonical: canonical for canonical in desired}
    assert dict(manifest.desired_phys) == desired
    assert seen_role_maps == {"left": expected, "right": expected}
    provenance = manifest.target_spec["provenance"]
    assert provenance["schema_version"] == "delta-minimize-color-target.v2"
    assert provenance["namespace_schema"] == "delta-minimize-role-namespace.v2"
    assert tuple(provenance["parent_role_bindings"]) == ("left", "right")


@pytest.mark.parametrize(
    "malformation",
    ["source-hash", "pcdump-hash", "absent-parent-ig", "wrong-class"],
)
def test_reviewed_parent_reanchor_rejects_invalid_bound_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    malformation: str,
) -> None:
    _left, right, target_spec, bindings, _aliases = _duplicate_role_inputs(
        monkeypatch,
        tmp_path,
        baseline_compile,
        desired_phys,
    )
    binding = bindings["right"]
    parent = right
    if malformation == "source-hash":
        binding = replace(binding, source_sha256="0" * 64)
    elif malformation == "pcdump-hash":
        binding = replace(binding, pcdump_sha256="0" * 64)
    elif malformation == "absent-parent-ig":
        mapping = dict(binding.canonical_to_parent)
        mapping[next(iter(mapping))] = 999999
        binding = replace(binding, canonical_to_parent=mapping)
    else:
        parent = replace(right, class_id=1)

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        objectives_module._reviewed_parent_reanchor(target_spec, parent, binding)


def test_reviewed_parent_reanchor_rejects_viable_nonminimum_semantic_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    _left, right, target_spec, bindings, aliases = _duplicate_role_inputs(
        monkeypatch,
        tmp_path,
        baseline_compile,
        desired_phys,
    )
    binding = bindings["right"]
    canonical = next(iter(binding.canonical_to_parent))
    selected = aliases[canonical]
    mapping = dict(binding.canonical_to_parent)
    mapping[canonical] = selected
    binding = replace(binding, canonical_to_parent=mapping)

    def controlled_cost(reference, candidate):
        if candidate.ig_idx == canonical:
            return 0.0
        if candidate.ig_idx == selected:
            return 0.1
        return 1.0

    monkeypatch.setattr(objectives_module.role_matcher, "role_cost", controlled_cost)

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        objectives_module._reviewed_parent_reanchor(target_spec, right, binding)


def test_v2_reviewed_role_map_rejects_full_profile_mapping_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target_spec, _bindings, aliases = _duplicate_role_inputs(
        monkeypatch,
        tmp_path,
        baseline_compile,
        desired_phys,
    )
    desired = {role.original_ig: role.desired_phys for role in target_spec.roles}
    canonical = next(iter(desired))
    target_path = _write_bound_v2_target(tmp_path, left, right, desired)

    def colliding_profile_map(_reference, parent, _class_id, **_kwargs):
        if parent is right.compile:
            return {aliases[canonical]: canonical}
        return {}

    monkeypatch.setattr(objectives_module, "_complete_profile_role_map", colliding_profile_map)

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-donor$"):
        infer_objective_manifest(
            left,
            right,
            target_path=target_path,
            donor_overrides={"objobjects": "left"},
            compile_loader=lambda *_args: left.compile,
        )


def test_duplicate_semantic_roles_remain_ambiguous_for_v1_and_automatic_derivation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target_spec, _bindings, _aliases = _duplicate_role_inputs(
        monkeypatch,
        tmp_path,
        baseline_compile,
        desired_phys,
    )
    desired = {role.original_ig: role.desired_phys for role in target_spec.roles}
    v1_target = _write_target(tmp_path, left.pcdump_path, desired)

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=v1_target,
            donor_overrides={"objobjects": "left"},
            compile_loader=lambda *_args: left.compile,
        )
    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=None,
            donor_overrides={"objobjects": "left"},
            derive_force_target=lambda *_args: _derivation_payload(desired),
        )


def test_correlated_allocator_orders_allow_complete_exact_graph_namespace(
    monkeypatch: pytest.MonkeyPatch,
    baseline_compile: Compile,
) -> None:
    peer_compile = deepcopy(baseline_compile)
    descriptors = build_descriptors(baseline_compile, 0)
    unique = {
        ig_idx: replace(descriptor, first_def_sig=f"ig:{ig_idx}:{descriptor.first_def_sig}")
        for ig_idx, descriptor in descriptors.items()
    }
    monkeypatch.setattr(objectives_module.role_descriptor, "build_descriptors", lambda *_args: unique)
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_virtual_semantic_identities",
        _complete_semantic_identities,
    )

    role_map = objectives_module._complete_profile_role_map(
        baseline_compile,
        peer_compile,
        0,
        allow_exact_namespace=True,
    )

    coalesce = [section for section in baseline_compile.fev.coalesce_sections if section.class_id == 0][-1]
    assert role_map == {ig_idx: ig_idx for ig_idx in range(coalesce.n_virtuals)}


def test_duplicate_semantic_roles_reject_exact_allocator_namespace(
    monkeypatch: pytest.MonkeyPatch,
    baseline_compile: Compile,
) -> None:
    virtual_count = baseline_compile.fev.coalesce_sections[-1].n_virtuals
    identities = _complete_semantic_identities(baseline_compile, 0, virtual_count)
    assert identities is not None
    identities[1] = identities[0]
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_virtual_semantic_identities",
        lambda *_args: None if len(set(identities.values())) != virtual_count else identities,
    )

    assert objectives_module._allocator_namespace_witness(baseline_compile, 0) is None


def test_divergent_allocator_order_rejects_exact_graph_namespace(
    monkeypatch: pytest.MonkeyPatch,
    baseline_compile: Compile,
) -> None:
    peer_compile = deepcopy(baseline_compile)
    simplify = [section for section in peer_compile.fev.simplify_sections if section.class_id == 0][-1]
    positive = [(index, entry) for index, entry in enumerate(simplify.entries) if entry.ig_idx >= 0]
    (first_index, first), (second_index, second) = positive[:2]
    simplify.entries[first_index] = replace(first, ig_idx=second.ig_idx)
    simplify.entries[second_index] = replace(second, ig_idx=first.ig_idx)
    monkeypatch.setattr(
        objectives_module.role_reanchor,
        "reanchor",
        lambda *_args, **_kwargs: type("Partial", (), {"matched": {}})(),
    )
    monkeypatch.setattr(
        objectives_module.role_descriptor,
        "build_virtual_semantic_identities",
        _complete_semantic_identities,
    )

    role_map = objectives_module._complete_profile_role_map(
        baseline_compile,
        peer_compile,
        0,
        allow_exact_namespace=True,
    )

    assert role_map == {}


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


@pytest.mark.parametrize(
    "contradiction",
    [
        "recommendation",
        "target-count",
        "runnable-count",
        "already-count",
        "needs-move-count",
        "unknown-count",
        "already-status",
        "unknown-status",
        "extra-force-entry",
    ],
)
def test_derived_actionability_envelope_contradictions_fail_closed(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    contradiction: str,
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left = _parent("left", baseline_compile, dump, desired_phys)
    right = _parent("right", baseline_compile, dump, desired_phys)
    payload = deepcopy(_derivation_payload(desired_phys))
    actionability = payload["actionability"]
    targets = payload["targets"]
    assert isinstance(actionability, dict)
    assert isinstance(targets, list)

    if contradiction == "recommendation":
        payload["force_vector_recommended"] = False
    elif contradiction == "target-count":
        actionability["target_count"] = len(targets) + 1
    elif contradiction == "runnable-count":
        actionability["runnable_target_count"] = len(targets) + 1
    elif contradiction == "already-count":
        actionability["already_target_count"] = 1
    elif contradiction == "needs-move-count":
        actionability["needs_move_count"] = 0
    elif contradiction == "unknown-count":
        actionability["unknown_current_count"] = 1
    elif contradiction == "already-status":
        for target in targets:
            target["current_reg"] = target["target_reg"]
            target["already_target"] = True
        actionability.update(
            status="needs-move",
            already_target_count=len(targets),
            needs_move_count=0,
        )
    elif contradiction == "unknown-status":
        for target in targets:
            target["current_reg"] = None
            target["already_target"] = None
        actionability.update(
            status="needs-move",
            needs_move_count=0,
            unknown_current_count=len(targets),
        )
    else:
        force_phys = payload["force_phys"]
        assert isinstance(force_phys, dict)
        force_phys["999999"] = 1

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=None,
            donor_overrides={"objobjects": "left"},
            derive_force_target=lambda *_: payload,
        )


def test_consistent_already_satisfied_derivation_envelope_is_accepted(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left = _parent("left", baseline_compile, dump, desired_phys)
    right = _parent("right", baseline_compile, dump, desired_phys)
    payload = _derivation_payload(desired_phys)
    targets = payload["targets"]
    actionability = payload["actionability"]
    assert isinstance(targets, list)
    assert isinstance(actionability, dict)
    for target_row in targets:
        target_row["current_reg"] = target_row["target_reg"]
        target_row["already_target"] = True
    actionability.update(
        status="already-satisfied",
        already_target_count=len(targets),
        needs_move_count=0,
    )
    payload["force_vector_recommended"] = False

    manifest = infer_objective_manifest(
        left,
        right,
        target_path=None,
        donor_overrides={"objobjects": "left"},
        derive_force_target=lambda *_: payload,
    )

    assert dict(manifest.desired_phys) == desired_phys


def test_explicit_target_reparses_declared_baseline_contents(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    left.pcdump_path.write_text("not a pcdump\n", encoding="utf-8")

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=target,
            donor_overrides={"objobjects": "left"},
        )


def test_explicit_target_uses_source_from_matching_right_parent(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump_text = (FIXTURES / "mnVibration_matched_pcdump.txt").read_text(encoding="utf-8")
    left_dump = tmp_path / "left.pcdump"
    right_dump = tmp_path / "right.pcdump"
    left_dump.write_text(dump_text, encoding="utf-8")
    right_dump.write_text(dump_text, encoding="utf-8")
    left_compile = Compile.from_text(dump_text, FUNCTION, "/* left source */")
    right_compile = Compile.from_text(dump_text, FUNCTION, "/* right source */")
    left = _parent("left", left_compile, left_dump, desired_phys)
    right = _parent("right", right_compile, right_dump, desired_phys)
    target = _write_target(tmp_path, right_dump, desired_phys)
    seen_sources: list[str] = []

    def load_baseline(path: Path, function: str, source: str) -> Compile:
        seen_sources.append(source)
        return Compile.from_text(path.read_text(encoding="utf-8"), function, source)

    infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"objobjects": "left"},
        compile_loader=load_baseline,
    )

    assert seen_sources == [right_compile.source]


def test_explicit_target_rejects_unknown_baseline_source_binding(
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
    loader_called = False

    def unexpected_loader(path: Path, function: str, source: str) -> Compile:
        nonlocal loader_called
        loader_called = True
        del path, function, source
        raise AssertionError("unknown baselines must fail before parsing with guessed source")

    with pytest.raises(DeltaMinimizeError, match="^ambiguous-color-target$"):
        infer_objective_manifest(
            left,
            right,
            target_path=target,
            donor_overrides={},
            compile_loader=unexpected_loader,
        )
    assert loader_called is False


def test_raw_color_profile_uses_roles_beyond_partial_force_target(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    left = replace(left, color_profile=None)
    right = replace(right, color_profile=None)
    seen_role_maps: list[dict[int, int]] = []

    def build_profile(
        pcdump: str,
        function: str,
        class_id: int,
        role_map: dict[int, int],
        required_roles: frozenset[int],
    ) -> ColorGraphProfile:
        del pcdump, function, class_id
        seen_role_maps.append(dict(role_map))
        stable_roles = tuple(sorted(set(role_map.values())))
        assignments = tuple((role, desired_phys.get(role, 0)) for role in stable_roles)
        return ColorGraphProfile(
            assignments=assignments,
            simplify_order=stable_roles,
            select_order=stable_roles,
            interference_edges=frozenset(),
            coalesce_pairs=frozenset(),
            spills=frozenset(),
            complete=required_roles <= set(stable_roles),
        )

    monkeypatch.setattr(
        "src.search.delta_minimize.objectives.build_colorgraph_profile",
        build_profile,
    )

    infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"objobjects": "left"},
    )

    assert len(seen_role_maps) == 2
    assert all(set(role_map.values()) > set(desired_phys) for role_map in seen_role_maps)


def test_derived_profile_preserves_semantically_reanchored_target_roles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    dump = tmp_path / "baseline.pcdump"
    dump.write_text("unused", encoding="utf-8")
    left_ig, right_ig = list(desired_phys)[:2]
    desired = {left_ig: 22}
    left = _parent("left", baseline_compile, dump, desired)
    right_compile = deepcopy(baseline_compile)
    right = _parent("right", right_compile, dump, desired)
    target_spec = role_descriptor.build_target_spec(
        baseline_compile,
        desired,
        0,
        "force_proof_proxy",
        {"inference": "parent-register-diff", "parent": "left"},
    )
    loaded = objectives_module.LoadedColorTarget(
        function=FUNCTION,
        class_id=0,
        baseline_dump=dump,
        force_phys=desired,
        coalesce_preservation=False,
    )
    monkeypatch.setattr(objectives_module, "_derive_target_spec", lambda *_args: (loaded, target_spec))
    exact_checks: list[tuple[Compile, bool]] = []

    def check_target(_target, compile, _class_id, _desired, *, exact_identity=False):
        exact_checks.append((compile, exact_identity))
        return objectives_module.role_reanchor.ReanchorResult(0, {}, {}, {})

    monkeypatch.setattr(
        objectives_module,
        "_require_complete_reanchor",
        check_target,
    )
    monkeypatch.setattr(
        objectives_module,
        "_complete_profile_role_map",
        lambda _reference, parent, _class_id, **_kwargs: (
            {left_ig: left_ig} if parent is baseline_compile else {right_ig: left_ig}
        ),
    )
    seen: dict[str, dict[int, int]] = {}

    def profile(parent, role_map, _desired):
        seen[parent.side] = dict(role_map)
        return _color_profile(desired)

    monkeypatch.setattr(objectives_module, "_profile_for_parent", profile)

    infer_objective_manifest(
        left,
        right,
        target_path=None,
        donor_overrides={"objobjects": "left"},
        derive_force_target=lambda *_args: {},
    )

    assert seen == {
        "left": {left_ig: left_ig},
        "right": {right_ig: left_ig},
    }
    assert exact_checks == [(baseline_compile, True), (right_compile, False)]


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
        stack_profile=_stack_profile(
            "compiler-temp:row-child",
            reference_kind="proxy",
        ),
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
        stack_profile=_stack_profile(
            "compiler-temp:row-child",
            reference_kind="proxy",
        ),
    )
    with pytest.raises(DeltaMinimizeError, match="ambiguous-stack-home-donor"):
        infer_objective_manifest(
            left,
            right,
            target_path=target,
            donor_overrides={"objobjects": "left"},
        )


@pytest.mark.parametrize(
    ("profile", "unresolved"),
    [
        (_stack_profile("compiler-temp:x", reference_kind="proxy"), ()),
        (
            _stack_profile("compiler-temp:x", reference_kind="proxy"),
            ("compiler-temp:y",),
        ),
        (_stack_profile(), ("symbol:x",)),
    ],
    ids=("proxy-omitted", "proxy-mismatched", "absolute-mislabeled-proxy"),
)
def test_stack_unresolved_must_exactly_match_proxy_home_identities(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    profile: StackHomeProfile,
    unresolved: tuple[str, ...],
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    malformed = replace(
        left,
        stack_home_profile=profile,
        stack_unresolved=unresolved,
    )

    with pytest.raises(DeltaMinimizeError, match="invalid-parent-stack-evidence"):
        infer_objective_manifest(
            malformed,
            right,
            target_path=target,
            donor_overrides={"objobjects": "left"},
        )


def test_all_absolute_stack_homes_record_strictly_closer_parent(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(
        tmp_path,
        baseline_compile,
        desired_phys,
        left_stack_distance=(0, 0, 0, 0),
        right_stack_distance=(1, 8, 0, 0),
    )

    manifest = infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"objobjects": "left"},
    )

    assert manifest.stack_home_donor == "left"
    assert manifest.references["stack-homes"].reference_kind == "absolute"
    assert manifest.references["stack-homes"].reference_artifact == "expected.o:frame"


def test_all_absolute_stack_home_override_selects_requested_parent(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
) -> None:
    left, right, target = _explicit_inputs(
        tmp_path,
        baseline_compile,
        desired_phys,
        left_stack_distance=(0, 0, 0, 0),
        right_stack_distance=(1, 8, 0, 0),
    )

    manifest = infer_objective_manifest(
        left,
        right,
        target_path=target,
        donor_overrides={"objobjects": "left", "stack-homes": "right"},
    )

    assert manifest.stack_home_donor == "right"
    stack_reference = manifest.references["stack-homes"]
    assert stack_reference.reference_kind == "absolute"
    assert stack_reference.reference_artifact == "expected.o:frame"
    assert stack_reference.override is True


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


@pytest.mark.parametrize(
    "malformation",
    [
        "color-complete-bool",
        "color-assignment-shape",
        "color-edge-shape",
        "objobject-complete-bool",
        "objobject-identity-value",
        "objobject-occurrence-shape",
        "stack-complete-bool",
        "stack-home-shape",
        "stack-home-value",
        "stack-blocker-shape",
    ],
)
def test_malformed_nested_parent_profiles_fail_closed(
    tmp_path: Path,
    baseline_compile: Compile,
    desired_phys: dict[int, int],
    malformation: str,
) -> None:
    left, right, target = _explicit_inputs(tmp_path, baseline_compile, desired_phys)
    color = left.color_profile
    assert color is not None

    if malformation == "color-complete-bool":
        malformed = replace(left, color_profile=replace(color, complete=1))
    elif malformation == "color-assignment-shape":
        malformed = replace(left, color_profile=replace(color, assignments=((1,),)))
    elif malformation == "color-edge-shape":
        malformed = replace(left, color_profile=replace(color, interference_edges=frozenset({(1,)})))
    elif malformation == "objobject-complete-bool":
        malformed = replace(left, objobject_profile=replace(left.objobject_profile, complete=1))
    elif malformation == "objobject-identity-value":
        identity = ObjObjectIdentity("local", 7, "int", FUNCTION, "x")
        malformed = replace(left, objobject_profile=ObjObjectProfile((identity,), True))
    elif malformation == "objobject-occurrence-shape":
        malformed = replace(
            left,
            objobject_profile=replace(left.objobject_profile, occurrence_evidence=(object(),)),
        )
    elif malformation == "stack-complete-bool":
        malformed = replace(left, stack_home_profile=replace(left.stack_home_profile, complete=1))
    elif malformation == "stack-home-shape":
        malformed = replace(left, stack_home_profile=replace(left.stack_home_profile, homes=[object()]))
    elif malformation == "stack-home-value":
        malformed_home = StackHome("symbol:x", True, 0, "absolute")
        malformed = replace(left, stack_home_profile=replace(left.stack_home_profile, homes=(malformed_home,)))
    else:
        malformed = replace(left, stack_home_profile=replace(left.stack_home_profile, blockers=["bad"]))

    with pytest.raises(DeltaMinimizeError):
        infer_objective_manifest(
            malformed,
            right,
            target_path=target,
            donor_overrides={"objobjects": "left"},
        )


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
    assert payload["schema_version"] == "delta-minimize-objectives.v2"
    assert payload["references"]["opcode"]["reference_artifact"] == "expected.o:draw"
    assert payload["references"]["opcode"]["reference_kind"] == "absolute"
    assert payload["references"]["color"]["override"] is True
    assert payload["desired_phys"] == {str(key): value for key, value in desired_phys.items()}
    with pytest.raises(TypeError):
        manifest.target_spec["provenance"]["mutated"] = True
