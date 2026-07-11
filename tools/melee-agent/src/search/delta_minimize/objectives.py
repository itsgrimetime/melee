"""Versioned color targets and immutable delta-search objective references."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

import yaml

from ...mwcc_debug import role_descriptor, role_reanchor
from ...mwcc_debug.colorgraph_profile import ColorGraphProfile, build_colorgraph_profile
from ...mwcc_debug.objobject_profile import ObjObjectIdentity, ObjObjectProfile
from ...mwcc_debug.stack_home_profile import StackHome, StackHomeProfile
from .contracts import DeltaMinimizeError

COLOR_TARGET_SCHEMA = "delta-minimize-color-target.v1"
OBJECTIVE_MANIFEST_SCHEMA = "delta-minimize-objectives.v1"
_TARGET_FIELDS = frozenset(
    {
        "schema_version",
        "function",
        "class_id",
        "baseline_dump",
        "force_phys",
        "coalesce_preservation",
    }
)
_DONOR_AXES = frozenset({"color", "objobjects", "stack-homes"})
_DONOR_VALUES = frozenset({"left", "right"})


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys at every depth."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _immutable_sorted_int_mapping(values: Mapping[int, int]) -> Mapping[int, int]:
    return MappingProxyType(dict(sorted(values.items())))


def _json_value(value: Any) -> Any:
    """Convert nested dataclass output into deterministic JSON-compatible data."""
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list, set, frozenset)):
        items = value if not isinstance(value, (set, frozenset)) else sorted(value)
        return [_json_value(item) for item in items]
    if isinstance(value, Path):
        return str(value)
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class LoadedColorTarget:
    function: str
    class_id: int
    baseline_dump: Path
    force_phys: Mapping[int, int]
    coalesce_preservation: bool


@dataclass(frozen=True)
class AxisReference:
    reference_kind: str
    reference_artifact: str
    donor: str | None
    inference_reason: str
    override: bool
    unresolved: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.reference_kind not in {"absolute", "proxy", "mixed"}:
            raise ValueError("invalid axis reference kind")
        if self.donor not in {None, "left", "right"}:
            raise ValueError("invalid axis reference donor")
        if not self.reference_artifact or not self.inference_reason:
            raise ValueError("incomplete axis reference provenance")
        if not isinstance(self.override, bool):
            raise TypeError("axis reference override must be boolean")
        normalized = tuple(sorted(set(self.unresolved)))
        if any(not isinstance(item, str) or not item for item in normalized):
            raise TypeError("axis reference unresolved identities must be strings")
        object.__setattr__(self, "unresolved", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_kind": self.reference_kind,
            "reference_artifact": self.reference_artifact,
            "donor": self.donor,
            "inference_reason": self.inference_reason,
            "override": self.override,
            "unresolved": list(self.unresolved),
        }


@dataclass(frozen=True)
class ObjectiveManifest:
    schema_version: str
    function: str
    class_id: int
    target_spec: Mapping[str, Any]
    desired_phys: Mapping[int, int]
    color_donor: str | None
    objobject_donor: str
    stack_home_donor: str | None
    references: Mapping[str, AxisReference]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "function": self.function,
            "class_id": self.class_id,
            "target_spec": _json_value(self.target_spec),
            "desired_phys": {str(role): physical for role, physical in sorted(self.desired_phys.items())},
            "color_donor": self.color_donor,
            "objobject_donor": self.objobject_donor,
            "stack_home_donor": self.stack_home_donor,
            "references": {axis: reference.to_dict() for axis, reference in sorted(self.references.items())},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class ParentObjectiveEvidence:
    """One retained parent's already-captured objective-inference evidence.

    Supplying ``color_profile`` is the cheap/injected test and resume path. If
    it is ``None``, inference builds the profile from ``pcdump_path`` after the
    target roles have been round-trip reanchored.
    """

    side: str
    function: str
    class_id: int
    compile: role_descriptor.Compile
    pcdump_path: Path
    expected_assembly: tuple[str, ...]
    current_assembly: tuple[str, ...]
    opcode_distance: tuple[int, int]
    color_profile: ColorGraphProfile | None
    objobject_profile: ObjObjectProfile
    stack_home_profile: StackHomeProfile
    stack_absolute_distance: tuple[int, int, int, int]
    stack_unresolved: tuple[str, ...]
    expected_assembly_artifact: str
    pcdump_artifact: str
    objobject_artifact: str
    stack_absolute_artifact: str
    stack_profile_artifact: str


ForceTargetDeriver = Callable[[list[str], list[str], Any, Any], Mapping[str, Any]]
CompileLoader = Callable[[Path, str, str], role_descriptor.Compile]


def _load_unique_yaml(path: Path) -> Mapping[str, Any]:
    try:
        documents = list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DeltaMinimizeError("ambiguous-color-target-yaml") from error
    if len(documents) != 1 or not isinstance(documents[0], Mapping):
        raise DeltaMinimizeError("ambiguous-color-target-yaml")
    return documents[0]


def _path_has_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _resolve_baseline_path(target_path: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise DeltaMinimizeError("invalid-color-target-baseline")
    candidate = Path(raw)
    if candidate.is_absolute():
        if _path_has_symlink(candidate):
            raise DeltaMinimizeError("invalid-color-target-baseline")
        baseline = candidate.resolve()
    else:
        root = target_path.parent.resolve()
        unresolved = root / candidate
        if _path_has_symlink(unresolved):
            raise DeltaMinimizeError("invalid-color-target-baseline")
        baseline = unresolved.resolve()
        if not baseline.is_relative_to(root):
            raise DeltaMinimizeError("invalid-color-target-baseline")
    if not baseline.is_file():
        raise DeltaMinimizeError("invalid-color-target-baseline")
    return baseline


def _validate_force_phys(raw: object) -> Mapping[int, int]:
    if not isinstance(raw, Mapping) or not raw:
        raise DeltaMinimizeError("invalid-color-target-force-phys")
    force_phys: dict[int, int] = {}
    for ig_idx, physical in raw.items():
        if not _is_int(ig_idx) or ig_idx < 0 or not _is_int(physical) or not 0 <= physical <= 31:
            raise DeltaMinimizeError("invalid-color-target-force-phys")
        force_phys[ig_idx] = physical
    return _immutable_sorted_int_mapping(force_phys)


def load_color_target(path: Path, *, function: str) -> LoadedColorTarget:
    """Load the exact, fail-closed ``delta-minimize-color-target.v1`` schema."""
    if not isinstance(path, Path) or _path_has_symlink(path.absolute()) or not path.is_file():
        raise DeltaMinimizeError("invalid-color-target-file")
    if not isinstance(function, str) or not function:
        raise DeltaMinimizeError("color-target-function-mismatch")
    data = _load_unique_yaml(path)
    if set(data) != _TARGET_FIELDS:
        raise DeltaMinimizeError("invalid-color-target-fields")
    if data["schema_version"] != COLOR_TARGET_SCHEMA:
        raise DeltaMinimizeError("unsupported-color-target-schema")
    if not isinstance(data["function"], str) or data["function"] != function:
        raise DeltaMinimizeError("color-target-function-mismatch")
    class_id = data["class_id"]
    if not _is_int(class_id) or class_id not in {0, 1}:
        raise DeltaMinimizeError("invalid-color-target-class")
    coalesce = data["coalesce_preservation"]
    if not isinstance(coalesce, bool):
        raise DeltaMinimizeError("invalid-color-target-coalesce-policy")
    return LoadedColorTarget(
        function=function,
        class_id=class_id,
        baseline_dump=_resolve_baseline_path(path, data["baseline_dump"]),
        force_phys=_validate_force_phys(data["force_phys"]),
        coalesce_preservation=coalesce,
    )


def _validate_distance(value: object, length: int, reason: str) -> tuple[int, ...]:
    if not isinstance(value, tuple) or len(value) != length or any(not _is_int(item) or item < 0 for item in value):
        raise DeltaMinimizeError(reason)
    return value


def _validate_role_pair(value: object, *, physical: bool = False) -> tuple[int, int] | None:
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    left, right = value
    if not _is_int(left) or left < 0 or not _is_int(right):
        return None
    if physical:
        if not 0 <= right <= 31:
            return None
    elif right < 0:
        return None
    return left, right


def _validate_color_profile(profile: ColorGraphProfile) -> None:
    if (
        type(profile.complete) is not bool
        or not isinstance(profile.assignments, tuple)
        or not isinstance(profile.simplify_order, tuple)
        or not isinstance(profile.select_order, tuple)
        or not isinstance(profile.interference_edges, frozenset)
        or not isinstance(profile.coalesce_pairs, frozenset)
        or not isinstance(profile.spills, frozenset)
        or not isinstance(profile.missing_roles, tuple)
    ):
        raise DeltaMinimizeError("invalid-parent-color-evidence")
    assignments = [_validate_role_pair(item, physical=True) for item in profile.assignments]
    simplify = profile.simplify_order
    select = profile.select_order
    edges = [_validate_role_pair(item) for item in profile.interference_edges]
    coalesces = [_validate_role_pair(item) for item in profile.coalesce_pairs]
    if (
        any(item is None for item in assignments)
        or any(not _is_int(role) or role < 0 for role in simplify)
        or any(not _is_int(role) or role < 0 for role in select)
        or any(item is None or item[0] >= item[1] for item in edges)
        or any(item is None or item[0] >= item[1] for item in coalesces)
        or any(not _is_int(role) or role < 0 for role in profile.spills)
        or any(not _is_int(role) or role < 0 for role in profile.missing_roles)
    ):
        raise DeltaMinimizeError("invalid-parent-color-evidence")
    assignment_roles = tuple(item[0] for item in assignments if item is not None)
    known_roles = set(assignment_roles)
    if (
        len(assignment_roles) != len(set(assignment_roles))
        or len(simplify) != len(set(simplify))
        or len(select) != len(set(select))
        or set(simplify) != known_roles
        or set(select) != known_roles
        or any(set(item) - known_roles for item in edges if item is not None)
        or any(set(item) - known_roles for item in coalesces if item is not None)
        or set(profile.spills) - known_roles
        or (profile.complete and profile.missing_roles)
    ):
        raise DeltaMinimizeError("invalid-parent-color-evidence")


def _validate_objobject_profile(profile: ObjObjectProfile) -> None:
    if (
        type(profile.complete) is not bool
        or not isinstance(profile.identities, tuple)
        or not isinstance(profile.occurrence_evidence, tuple)
        or (profile.blocker is not None and (not isinstance(profile.blocker, str) or not profile.blocker))
        or (profile.complete and profile.blocker is not None)
        or (profile.occurrence_evidence and len(profile.occurrence_evidence) != len(profile.identities))
    ):
        raise DeltaMinimizeError("invalid-parent-objobject-evidence")
    for identity in profile.identities:
        if not isinstance(identity, ObjObjectIdentity):
            raise DeltaMinimizeError("invalid-parent-objobject-evidence")
        if any(
            not isinstance(value, str) or not value
            for value in (
                identity.kind,
                identity.source_name,
                identity.type_name,
                identity.scope,
                identity.expression,
            )
        ):
            raise DeltaMinimizeError("invalid-parent-objobject-evidence")
    if any(item is not None and (not isinstance(item, str) or not item) for item in profile.occurrence_evidence):
        raise DeltaMinimizeError("invalid-parent-objobject-evidence")


def _validate_stack_home_profile(profile: StackHomeProfile) -> None:
    if (
        type(profile.complete) is not bool
        or not isinstance(profile.homes, tuple)
        or not isinstance(profile.blockers, tuple)
        or (profile.frame_size is not None and (not _is_int(profile.frame_size) or profile.frame_size < 0))
        or (profile.complete and profile.frame_size is None)
        or any(not isinstance(blocker, str) or not blocker for blocker in profile.blockers)
        or (profile.complete and profile.blockers)
    ):
        raise DeltaMinimizeError("invalid-parent-stack-evidence")
    identities: list[str] = []
    orders: list[int] = []
    for home in profile.homes:
        if (
            not isinstance(home, StackHome)
            or not isinstance(home.identity, str)
            or not home.identity
            or not _is_int(home.offset)
            or not _is_int(home.order)
            or home.order < 0
            or home.reference_kind not in {"absolute", "proxy"}
        ):
            raise DeltaMinimizeError("invalid-parent-stack-evidence")
        identities.append(home.identity)
        orders.append(home.order)
    if len(identities) != len(set(identities)) or sorted(orders) != list(range(len(orders))):
        raise DeltaMinimizeError("invalid-parent-stack-evidence")


def _validate_parent(parent: ParentObjectiveEvidence, expected_side: str) -> None:
    if not isinstance(parent, ParentObjectiveEvidence) or parent.side != expected_side:
        raise DeltaMinimizeError("invalid-parent-evidence")
    if (
        not isinstance(parent.compile, role_descriptor.Compile)
        or not isinstance(parent.pcdump_path, Path)
        or not isinstance(parent.function, str)
        or parent.function != parent.compile.name
        or not _is_int(parent.class_id)
        or parent.class_id not in {0, 1}
        or not parent.pcdump_path.is_file()
        or not isinstance(parent.expected_assembly, tuple)
        or not parent.expected_assembly
        or any(not isinstance(line, str) or not line for line in parent.expected_assembly)
        or not isinstance(parent.current_assembly, tuple)
        or not parent.current_assembly
        or any(not isinstance(line, str) or not line for line in parent.current_assembly)
        or (parent.color_profile is not None and not isinstance(parent.color_profile, ColorGraphProfile))
        or not isinstance(parent.objobject_profile, ObjObjectProfile)
        or not isinstance(parent.stack_home_profile, StackHomeProfile)
        or not isinstance(parent.stack_unresolved, tuple)
    ):
        raise DeltaMinimizeError("invalid-parent-evidence")
    if parent.color_profile is not None:
        _validate_color_profile(parent.color_profile)
    _validate_objobject_profile(parent.objobject_profile)
    _validate_stack_home_profile(parent.stack_home_profile)
    for artifact in (
        parent.expected_assembly_artifact,
        parent.pcdump_artifact,
        parent.objobject_artifact,
        parent.stack_absolute_artifact,
        parent.stack_profile_artifact,
    ):
        if not isinstance(artifact, str) or not artifact:
            raise DeltaMinimizeError("invalid-parent-evidence")
    _validate_distance(parent.opcode_distance, 2, "invalid-parent-opcode-distance")
    _validate_distance(parent.stack_absolute_distance, 4, "invalid-parent-stack-distance")
    if any(not isinstance(item, str) or not item for item in parent.stack_unresolved):
        raise DeltaMinimizeError("invalid-parent-stack-evidence")
    if not parent.objobject_profile.complete:
        raise DeltaMinimizeError("incomplete-objobject-evidence")
    if not parent.stack_home_profile.complete:
        raise DeltaMinimizeError("incomplete-stack-home-evidence")


def _validate_overrides(overrides: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(overrides, Mapping):
        raise DeltaMinimizeError("invalid-donor-override")
    if set(overrides) - _DONOR_AXES:
        raise DeltaMinimizeError("invalid-donor-override")
    result: dict[str, str] = {}
    for axis, donor in overrides.items():
        if not isinstance(axis, str) or not isinstance(donor, str) or donor not in _DONOR_VALUES:
            raise DeltaMinimizeError("invalid-donor-override")
        result[axis] = donor
    return result


def _default_compile_loader(path: Path, function: str, source: str) -> role_descriptor.Compile:
    return role_descriptor.Compile.from_text(path.read_text(encoding="utf-8"), function, source)


def _target_spec(
    compile: role_descriptor.Compile,
    force_phys: Mapping[int, int],
    class_id: int,
    provenance: Mapping[str, Any],
    coalesce_preservation: bool,
) -> role_descriptor.TargetSpec:
    return role_descriptor.build_target_spec(
        compile,
        dict(force_phys),
        class_id,
        "force_proof_proxy",
        provenance=dict(provenance),
        causal_closure=coalesce_preservation,
    )


def _require_complete_reanchor(
    target: role_descriptor.TargetSpec,
    compile: role_descriptor.Compile,
    class_id: int,
    desired_phys: Mapping[int, int],
) -> role_reanchor.ReanchorResult:
    result = role_reanchor.reanchor(target, compile, class_id=class_id)
    landed: dict[int, tuple[int, int]] = {}
    for new_ig, original_ig in result.matched.items():
        if original_ig in desired_phys and new_ig in result.force_phys:
            if original_ig in landed:
                raise DeltaMinimizeError("ambiguous-color-target")
            landed[original_ig] = (new_ig, result.force_phys[new_ig])
    if set(landed) != set(desired_phys):
        raise DeltaMinimizeError("ambiguous-color-target")
    if any(landed[role][1] != physical for role, physical in desired_phys.items()):
        raise DeltaMinimizeError("ambiguous-color-target")
    if any(role in result.diagnostics for role in desired_phys):
        raise DeltaMinimizeError("ambiguous-color-target")
    return result


def _compile_for_explicit_target(
    target: LoadedColorTarget,
    left: ParentObjectiveEvidence,
    right: ParentObjectiveEvidence,
    compile_loader: CompileLoader,
) -> role_descriptor.Compile:
    try:
        baseline = compile_loader(target.baseline_dump, target.function, left.compile.source)
        if not isinstance(baseline, role_descriptor.Compile) or baseline.name != target.function:
            raise ValueError("baseline compile does not contain target function")
        return baseline
    except Exception as error:
        raise DeltaMinimizeError("ambiguous-color-target") from error


def _parse_derived_ig(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    if value == "0":
        return 0
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        return None
    return int(value)


def _force_phys_from_derivation(payload: object, class_id: int) -> Mapping[int, int]:
    """Validate and extract one class from the real register-diff envelope."""
    if not isinstance(payload, Mapping):
        raise DeltaMinimizeError("ambiguous-color-target")
    force_payload = payload.get("force_phys")
    targets = payload.get("targets")
    conflicts = payload.get("conflicts")
    actionability = payload.get("actionability")
    recommended = payload.get("force_vector_recommended")
    if (
        not isinstance(force_payload, Mapping)
        or not isinstance(targets, list)
        or not isinstance(conflicts, list)
        or not isinstance(actionability, Mapping)
        or not isinstance(recommended, bool)
    ):
        raise DeltaMinimizeError("ambiguous-color-target")

    conflict_keys: set[tuple[int, str, int]] = set()
    conflict_existing: dict[tuple[int, str, int], int] = {}
    for conflict in conflicts:
        if not isinstance(conflict, Mapping):
            raise DeltaMinimizeError("ambiguous-color-target")
        conflict_class = conflict.get("class_id")
        conflict_kind = conflict.get("kind")
        conflict_ig = conflict.get("ig_idx")
        existing_phys = conflict.get("existing_phys")
        conflicting_phys = conflict.get("conflicting_phys")
        if (
            not _is_int(conflict_class)
            or conflict_class not in {0, 1}
            or conflict_kind != ("r" if conflict_class == 0 else "f")
            or not _is_int(conflict_ig)
            or conflict_ig < 0
            or not _is_int(existing_phys)
            or not 0 <= existing_phys <= 31
            or not _is_int(conflicting_phys)
            or not 0 <= conflicting_phys <= 31
            or existing_phys == conflicting_phys
        ):
            raise DeltaMinimizeError("ambiguous-color-target")
        key = (conflict_class, conflict_kind, conflict_ig)
        if key in conflict_keys:
            raise DeltaMinimizeError("ambiguous-color-target")
        conflict_keys.add(key)
        conflict_existing[key] = existing_phys
        if conflict_class == class_id:
            raise DeltaMinimizeError("ambiguous-color-target")

    envelope_force: dict[int, int] = {}
    for raw_ig, physical in force_payload.items():
        ig_idx = _parse_derived_ig(raw_ig)
        if ig_idx is None or not _is_int(physical) or not 0 <= physical <= 31:
            raise DeltaMinimizeError("ambiguous-color-target")
        envelope_force[ig_idx] = physical

    expected_kind = "r" if class_id == 0 else "f"
    class_force: dict[int, int] = {}
    target_keys: set[tuple[int, str, int]] = set()
    expected_envelope_force: dict[int, int] = {}
    runnable_count = 0
    already_count = 0
    needs_move_count = 0
    unknown_count = 0
    for target in targets:
        if not isinstance(target, Mapping):
            raise DeltaMinimizeError("ambiguous-color-target")
        target_class = target.get("class_id")
        if not _is_int(target_class) or target_class not in {0, 1}:
            raise DeltaMinimizeError("ambiguous-color-target")
        target_kind = target.get("kind")
        if target_kind != ("r" if target_class == 0 else "f"):
            raise DeltaMinimizeError("ambiguous-color-target")
        ig_idx = target.get("ig_idx")
        physical = target.get("target_reg")
        runnable = target.get("force_vector_runnable")
        current_reg = target.get("current_reg")
        already_target = target.get("already_target")
        if (
            not _is_int(ig_idx)
            or ig_idx < 0
            or not _is_int(physical)
            or not 0 <= physical <= 31
            or target.get("confidence") not in {"exact", "current-reg"}
            or type(runnable) is not bool
            or (current_reg is not None and (not _is_int(current_reg) or not 0 <= current_reg <= 31))
            or (already_target is not None and type(already_target) is not bool)
            or (current_reg is None) != (already_target is None)
            or (current_reg is not None and already_target is not (current_reg == physical))
        ):
            raise DeltaMinimizeError("ambiguous-color-target")
        key = (target_class, target_kind, ig_idx)
        if (
            key in target_keys
            or runnable is (key in conflict_keys)
            or (key in conflict_existing and conflict_existing[key] != physical)
        ):
            raise DeltaMinimizeError("ambiguous-color-target")
        target_keys.add(key)
        if runnable:
            runnable_count += 1
            previous_force = expected_envelope_force.get(ig_idx)
            if previous_force is not None and previous_force != physical:
                raise DeltaMinimizeError("ambiguous-color-target")
            expected_envelope_force[ig_idx] = physical
            if already_target is True:
                already_count += 1
            elif already_target is False:
                needs_move_count += 1
            else:
                unknown_count += 1
        if target_class != class_id:
            continue
        if not runnable or target_kind != expected_kind or envelope_force.get(ig_idx) != physical:
            raise DeltaMinimizeError("ambiguous-color-target")
        previous = class_force.get(ig_idx)
        if previous is not None and previous != physical:
            raise DeltaMinimizeError("ambiguous-color-target")
        class_force[ig_idx] = physical

    if conflict_keys - target_keys or envelope_force != expected_envelope_force:
        raise DeltaMinimizeError("ambiguous-color-target")

    status = actionability.get("status")
    counts = {
        "target_count": len(targets),
        "runnable_target_count": runnable_count,
        "already_target_count": already_count,
        "needs_move_count": needs_move_count,
        "unknown_current_count": unknown_count,
    }
    expected_status: str
    if runnable_count and not needs_move_count and not unknown_count:
        expected_status = "already-satisfied"
    elif needs_move_count:
        expected_status = "needs-move"
    elif unknown_count:
        expected_status = "current-unknown"
    else:
        expected_status = "no-runnable-targets"
    expected_recommended = expected_status not in {
        "already-satisfied",
        "no-runnable-targets",
    }
    if (
        not class_force
        or status != expected_status
        or recommended is not expected_recommended
        or any(
            not _is_int(actionability.get(name)) or actionability.get(name) != value for name, value in counts.items()
        )
    ):
        raise DeltaMinimizeError("ambiguous-color-target")
    return _immutable_sorted_int_mapping(class_force)


def _derive_target_spec(
    left: ParentObjectiveEvidence,
    right: ParentObjectiveEvidence,
    derive_force_target: ForceTargetDeriver | None,
) -> tuple[LoadedColorTarget, role_descriptor.TargetSpec]:
    if derive_force_target is None:
        raise DeltaMinimizeError("ambiguous-color-target")
    derived: list[Mapping[int, int]] = []
    specs: list[role_descriptor.TargetSpec] = []
    for parent in (left, right):
        try:
            payload = derive_force_target(
                list(parent.expected_assembly),
                list(parent.current_assembly),
                parent.compile.fn.last_precolor_pass(),
                parent.compile.fev,
            )
            force_phys = _force_phys_from_derivation(payload, parent.class_id)
        except DeltaMinimizeError as error:
            raise DeltaMinimizeError("ambiguous-color-target") from error
        except Exception as error:
            raise DeltaMinimizeError("ambiguous-color-target") from error
        spec = _target_spec(
            parent.compile,
            force_phys,
            parent.class_id,
            {"inference": "parent-register-diff", "parent": parent.side},
            False,
        )
        _require_complete_reanchor(spec, parent.compile, parent.class_id, force_phys)
        derived.append(force_phys)
        specs.append(spec)

    left_to_right = _require_complete_reanchor(specs[0], right.compile, left.class_id, derived[0])
    right_to_left = _require_complete_reanchor(specs[1], left.compile, right.class_id, derived[1])
    if left.class_id != right.class_id:
        raise DeltaMinimizeError("ambiguous-color-target")
    if dict(left_to_right.force_phys) != dict(derived[1]):
        raise DeltaMinimizeError("ambiguous-color-target")
    if dict(right_to_left.force_phys) != dict(derived[0]):
        raise DeltaMinimizeError("ambiguous-color-target")
    target = LoadedColorTarget(
        function=left.function,
        class_id=left.class_id,
        baseline_dump=left.pcdump_path.resolve(),
        force_phys=derived[0],
        coalesce_preservation=False,
    )
    return target, specs[0]


def _profile_for_parent(
    parent: ParentObjectiveEvidence,
    reanchored: role_reanchor.ReanchorResult,
    desired_phys: Mapping[int, int],
) -> ColorGraphProfile:
    profile = parent.color_profile
    if profile is None:
        try:
            profile = build_colorgraph_profile(
                parent.pcdump_path.read_text(encoding="utf-8"),
                parent.function,
                parent.class_id,
                reanchored.matched,
                required_roles=frozenset(desired_phys),
            )
        except (OSError, UnicodeError, ValueError) as error:
            raise DeltaMinimizeError("ambiguous-color-donor") from error
    assignments = [role for role, _physical in profile.assignments]
    if (
        not profile.complete
        or set(desired_phys) - set(assignments)
        or set(desired_phys) - set(profile.simplify_order)
        or set(desired_phys) - set(profile.select_order)
    ):
        raise DeltaMinimizeError("ambiguous-color-donor")
    return profile


def _assignment_distance(profile: ColorGraphProfile, desired_phys: Mapping[int, int]) -> int:
    assignments = dict(profile.assignments)
    return sum(assignments.get(role) != physical for role, physical in desired_phys.items())


def _secondary_color_profile(profile: ColorGraphProfile) -> tuple[Any, ...]:
    return (
        profile.simplify_order,
        profile.select_order,
        profile.interference_edges,
        profile.coalesce_pairs,
        profile.spills,
    )


def _select_color_donor(
    left: ColorGraphProfile,
    right: ColorGraphProfile,
    desired_phys: Mapping[int, int],
    override: str | None,
) -> tuple[str | None, str]:
    if override is not None:
        return override, "explicit-color-donor-override"
    left_distance = _assignment_distance(left, desired_phys)
    right_distance = _assignment_distance(right, desired_phys)
    if left_distance < right_distance:
        return "left", "lower-desired-assignment-distance"
    if right_distance < left_distance:
        return "right", "lower-desired-assignment-distance"
    if _secondary_color_profile(left) == _secondary_color_profile(right):
        return None, "equal-assignment-distance-identical-secondary-profiles"
    raise DeltaMinimizeError("ambiguous-color-donor")


def _select_stack_donor(
    left: ParentObjectiveEvidence,
    right: ParentObjectiveEvidence,
    override: str | None,
) -> tuple[str | None, tuple[str, ...], str]:
    left_unresolved = tuple(sorted(set(left.stack_unresolved)))
    right_unresolved = tuple(sorted(set(right.stack_unresolved)))
    if left_unresolved != right_unresolved:
        raise DeltaMinimizeError("ambiguous-stack-home-donor")
    if not left_unresolved:
        if override is not None:
            raise DeltaMinimizeError("invalid-donor-override")
        return None, (), "all-stack-homes-have-absolute-references"
    if override is not None:
        return override, left_unresolved, "explicit-stack-home-donor-override"
    if left.stack_absolute_distance < right.stack_absolute_distance:
        return "left", left_unresolved, "strictly-lower-stack-home-distance"
    if right.stack_absolute_distance < left.stack_absolute_distance:
        return "right", left_unresolved, "strictly-lower-stack-home-distance"
    raise DeltaMinimizeError("ambiguous-stack-home-donor")


def _artifact_with_donor(absolute: str, donor_artifact: str | None) -> str:
    if donor_artifact is None:
        return absolute
    return f"absolute={absolute};secondary={donor_artifact}"


def infer_objective_manifest(
    left: ParentObjectiveEvidence,
    right: ParentObjectiveEvidence,
    *,
    target_path: Path | None,
    donor_overrides: Mapping[str, str],
    derive_force_target: ForceTargetDeriver | None = None,
    compile_loader: CompileLoader | None = None,
) -> ObjectiveManifest:
    """Infer one immutable objective manifest from two retained parents."""
    _validate_parent(left, "left")
    _validate_parent(right, "right")
    if left.function != right.function or left.class_id != right.class_id:
        raise DeltaMinimizeError("invalid-parent-evidence")
    if left.expected_assembly != right.expected_assembly:
        raise DeltaMinimizeError("ambiguous-opcode-target")
    if left.stack_absolute_artifact != right.stack_absolute_artifact:
        raise DeltaMinimizeError("invalid-parent-stack-evidence")
    overrides = _validate_overrides(donor_overrides)

    if target_path is None:
        loaded, target_spec = _derive_target_spec(left, right, derive_force_target)
        color_target_artifact = "derived-parent-register-diff"
        target_reason = "cross-parent-round-trip-derived-target"
    else:
        loaded = load_color_target(target_path, function=left.function)
        if loaded.class_id != left.class_id:
            raise DeltaMinimizeError("color-target-class-mismatch")
        baseline_compile = _compile_for_explicit_target(
            loaded,
            left,
            right,
            compile_loader or _default_compile_loader,
        )
        target_spec = _target_spec(
            baseline_compile,
            loaded.force_phys,
            loaded.class_id,
            {
                "schema_version": COLOR_TARGET_SCHEMA,
                "baseline_dump": str(loaded.baseline_dump),
            },
            loaded.coalesce_preservation,
        )
        _require_complete_reanchor(
            target_spec,
            baseline_compile,
            loaded.class_id,
            loaded.force_phys,
        )
        color_target_artifact = str(target_path.resolve())
        target_reason = "explicit-versioned-color-target"

    left_reanchor = _require_complete_reanchor(
        target_spec,
        left.compile,
        loaded.class_id,
        loaded.force_phys,
    )
    right_reanchor = _require_complete_reanchor(
        target_spec,
        right.compile,
        loaded.class_id,
        loaded.force_phys,
    )
    left_color = _profile_for_parent(left, left_reanchor, loaded.force_phys)
    right_color = _profile_for_parent(right, right_reanchor, loaded.force_phys)

    color_donor, color_reason = _select_color_donor(
        left_color,
        right_color,
        loaded.force_phys,
        overrides.get("color"),
    )
    objobject_donor = overrides.get("objobjects") or color_donor
    if objobject_donor is None:
        raise DeltaMinimizeError("ambiguous-objobject-donor")
    objobject_reason = (
        "explicit-objobject-donor-override" if "objobjects" in overrides else "inherits-selected-color-donor"
    )
    stack_donor, stack_unresolved, stack_reason = _select_stack_donor(
        left,
        right,
        overrides.get("stack-homes"),
    )

    opcode_donor: str | None
    if left.opcode_distance < right.opcode_distance:
        opcode_donor = "left"
        opcode_reason = "expected-assembly-absolute;left-parent-closer"
    elif right.opcode_distance < left.opcode_distance:
        opcode_donor = "right"
        opcode_reason = "expected-assembly-absolute;right-parent-closer"
    else:
        opcode_donor = None
        opcode_reason = "expected-assembly-absolute;equal-parent-distance"

    parents = {"left": left, "right": right}
    if color_donor is None:
        color_artifact = (
            f"absolute={color_target_artifact};secondary=identical({left.pcdump_artifact},{right.pcdump_artifact})"
        )
    else:
        color_artifact = _artifact_with_donor(
            color_target_artifact,
            parents[color_donor].pcdump_artifact,
        )
    stack_artifact = _artifact_with_donor(
        left.stack_absolute_artifact,
        parents[stack_donor].stack_profile_artifact if stack_donor is not None else None,
    )
    references = MappingProxyType(
        {
            "color": AxisReference(
                "mixed",
                color_artifact,
                color_donor,
                f"{target_reason};{color_reason}",
                "color" in overrides,
            ),
            "objobjects": AxisReference(
                "proxy",
                parents[objobject_donor].objobject_artifact,
                objobject_donor,
                objobject_reason,
                "objobjects" in overrides,
            ),
            "opcode": AxisReference(
                "absolute",
                left.expected_assembly_artifact,
                opcode_donor,
                opcode_reason,
                False,
            ),
            "stack-homes": AxisReference(
                "mixed" if stack_unresolved else "absolute",
                stack_artifact,
                stack_donor,
                stack_reason,
                "stack-homes" in overrides,
                stack_unresolved,
            ),
        }
    )
    return ObjectiveManifest(
        schema_version=OBJECTIVE_MANIFEST_SCHEMA,
        function=loaded.function,
        class_id=loaded.class_id,
        target_spec=_freeze(asdict(target_spec)),
        desired_phys=_immutable_sorted_int_mapping(loaded.force_phys),
        color_donor=color_donor,
        objobject_donor=objobject_donor,
        stack_home_donor=stack_donor,
        references=references,
    )
