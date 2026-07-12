"""Ordered, resumable orchestration for closed-world delta minimization."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from itertools import zip_longest
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ...layout.objects import unit_paths
from ...mwcc_debug import role_descriptor
from ...mwcc_debug.objobject_profile import ObjObjectProfile, parse_objobject_profile
from ...mwcc_debug.opcode_graph import opcode_graph_distance, parse_opcode_graph
from ...mwcc_debug.source_candidate_scoring import ScoreSourceConfig
from ...mwcc_debug.stack_home_profile import build_stack_home_profile, stack_home_distance
from .contracts import CandidateProfile, DeltaMinimizeError, ParetoSummary
from .delta import (
    DeltaAtom,
    DeltaManifest,
    DeltaPatch,
    MaterializedCandidate,
    enumerate_legal_masks,
    extract_delta_manifest,
    materialize_mask,
)
from .evaluator import (
    CandidateEvaluationConfig,
    EvaluationBackends,
    ParentEvidenceBundle,
    RawCandidateEvidence,
    _candidate_blockers,
    _compile_diagnostics,
    _compile_rejected,
    _evidence_frame_and_stack,
    _file_hash,
    _frame_and_stack,
    _invoke_inspector,
    _structural_status,
    _validate_cached_artifacts,
    capture_candidate,
    default_evaluation_backends,
    profile_candidate,
)
from .objectives import (
    COLOR_TARGET_SCHEMA,
    OBJECTIVE_MANIFEST_SCHEMA,
    AxisReference,
    ObjectiveManifest,
    ParentObjectiveEvidence,
    infer_objective_manifest,
    load_color_target,
)
from .pareto import reduce_pareto
from .store import DeltaRunStore

PARSER_SCHEMA_HASH = "opcode.v1+color.v1+objobjects.v1+stack-homes.v1"
RESULT_SCHEMA = "delta-minimize-result.v1"
OBJECTIVE_INPUTS_SCHEMA = "delta-minimize-objective-inputs.v2"
_OBJECTIVE_AXES = frozenset({"opcode", "color", "objobjects", "stack-homes"})
_DONOR_OVERRIDE_AXES = frozenset({"color", "objobjects", "stack-homes"})
_REGISTER_CLASSES = frozenset({0, 1})
_REFERENCE_FIELDS = frozenset(
    {
        "reference_kind",
        "reference_artifact",
        "donor",
        "inference_reason",
        "override",
        "unresolved",
    }
)
_OBJECTIVE_FIELDS = frozenset(
    {
        "schema_version",
        "function",
        "class_id",
        "target_spec",
        "desired_phys",
        "color_donor",
        "objobject_donor",
        "stack_home_donor",
        "references",
    }
)
_DELTA_MANIFEST_FIELDS = frozenset({"schema_version", "function", "left_hash", "right_hash", "atoms"})
_DELTA_ATOM_FIELDS = frozenset({"atom_id", "kind", "patches", "requires", "affected_functions", "summary"})
_DELTA_PATCH_FIELDS = frozenset(
    {
        "left_start",
        "left_end",
        "left_text",
        "right_start",
        "right_end",
        "right_text",
        "anchor_kind",
        "anchor_symbol",
    }
)


def _canonical_donor_overrides(payload: object) -> dict[str, str]:
    if not isinstance(payload, Mapping) or set(payload) - _DONOR_OVERRIDE_AXES:
        raise ValueError
    overrides: dict[str, str] = {}
    for axis, donor in payload.items():
        if not isinstance(axis, str) or not isinstance(donor, str) or donor not in {"left", "right"}:
            raise ValueError
        overrides[axis] = donor
    return dict(sorted(overrides.items()))


@dataclass(frozen=True)
class DeltaMinimizeConfig:
    function: str
    left: Path
    right: Path
    out_dir: Path
    max_candidates: int
    target_path: Path | None
    donor_overrides: Mapping[str, str]
    include_objobjects: bool
    melee_root: Path
    cflags_from: Path

    def __post_init__(self) -> None:
        paths = (self.left, self.right, self.out_dir, self.melee_root, self.cflags_from)
        if (
            not isinstance(self.function, str)
            or not self.function
            or any(not isinstance(path, Path) for path in paths)
            or (self.target_path is not None and not isinstance(self.target_path, Path))
            or not isinstance(self.max_candidates, int)
            or isinstance(self.max_candidates, bool)
            or self.max_candidates < 1
            or not isinstance(self.include_objobjects, bool)
        ):
            raise DeltaMinimizeError("invalid-delta-minimize-config")
        try:
            overrides = _canonical_donor_overrides(self.donor_overrides)
        except ValueError as error:
            raise DeltaMinimizeError("invalid-delta-minimize-config") from error
        object.__setattr__(self, "donor_overrides", MappingProxyType(overrides))


@dataclass(frozen=True)
class DeltaMinimizeResult:
    schema_version: str
    status: str
    exact_four_axis: bool
    function: str
    objective_manifest: Mapping[str, Any]
    delta_manifest: Mapping[str, Any]
    candidate_counts: Mapping[str, int]
    candidates: tuple[Mapping[str, Any], ...]
    pareto: ParetoSummary | None
    best_next: str | None
    cache_stats: Mapping[str, int]
    blockers: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    compiler_provenance: Mapping[str, Any] = field(default_factory=dict)
    candidate_budget: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "exact_four_axis": self.exact_four_axis,
            "function": self.function,
            "inputs": _json_value(self.inputs),
            "compiler_provenance": _json_value(self.compiler_provenance),
            "objective_manifest": _json_value(self.objective_manifest),
            "delta_manifest": _json_value(self.delta_manifest),
            "candidate_counts": dict(sorted(self.candidate_counts.items())),
            "candidate_budget": self.candidate_budget,
            "candidates": [_json_value(row) for row in self.candidates],
            "pareto": None if self.pareto is None else self.pareto.to_dict(),
            "best_next": self.best_next,
            "cache_stats": dict(sorted(self.cache_stats.items())),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class DeltaMinimizeBackends:
    """Injectable outer effects; enumeration and cache policy stay in the run."""

    parent_provenance: Callable[[DeltaMinimizeConfig], Mapping[str, str]]
    capture_parent: Callable[[MaterializedCandidate, DeltaMinimizeConfig, DeltaRunStore], RawCandidateEvidence]
    parent_objective: Callable[[RawCandidateEvidence, str, DeltaMinimizeConfig], Any]
    infer_objective: Callable[[Any, Any, DeltaMinimizeConfig], ObjectiveManifest]
    evaluation: EvaluationBackends
    profile_candidate: Callable[..., CandidateProfile] = profile_candidate
    extract_manifest: Callable[..., DeltaManifest] = extract_delta_manifest


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"not JSON-compatible: {type(value).__name__}")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _hash_json(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _read_source(path: Path, *, side: str) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise DeltaMinimizeError("invalid-source-input", {"side": side, "path": str(path)}) from error


def _patch_to_dict(patch: DeltaPatch) -> dict[str, Any]:
    return {
        "left_start": patch.left_start,
        "left_end": patch.left_end,
        "left_text": patch.left_text,
        "right_start": patch.right_start,
        "right_end": patch.right_end,
        "right_text": patch.right_text,
        "anchor_kind": patch.anchor_kind,
        "anchor_symbol": patch.anchor_symbol,
    }


def _manifest_to_dict(manifest: DeltaManifest) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "function": manifest.function,
        "left_hash": manifest.left_hash,
        "right_hash": manifest.right_hash,
        "atoms": [
            {
                "atom_id": atom.atom_id,
                "kind": atom.kind,
                "patches": [_patch_to_dict(patch) for patch in atom.patches],
                "requires": list(atom.requires),
                "affected_functions": list(atom.affected_functions),
                "summary": atom.summary,
            }
            for atom in manifest.atoms
        ],
    }


def _manifest_from_dict(payload: Mapping[str, Any]) -> DeltaManifest:
    try:
        if set(payload) != _DELTA_MANIFEST_FIELDS:
            raise ValueError
        if (
            payload["schema_version"] != "delta-manifest.v1"
            or not isinstance(payload["function"], str)
            or not payload["function"]
            or not _is_digest(payload["left_hash"])
            or not _is_digest(payload["right_hash"])
            or not isinstance(payload["atoms"], list)
        ):
            raise ValueError
        for row in payload["atoms"]:
            if (
                not isinstance(row, Mapping)
                or set(row) != _DELTA_ATOM_FIELDS
                or not isinstance(row["atom_id"], str)
                or not row["atom_id"]
                or not isinstance(row["kind"], str)
                or not row["kind"]
                or not isinstance(row["patches"], list)
                or not isinstance(row["requires"], list)
                or not all(isinstance(item, str) and item for item in row["requires"])
                or not isinstance(row["affected_functions"], list)
                or not all(isinstance(item, str) and item for item in row["affected_functions"])
                or not isinstance(row["summary"], str)
            ):
                raise ValueError
            for patch in row["patches"]:
                if not isinstance(patch, Mapping) or set(patch) != _DELTA_PATCH_FIELDS:
                    raise ValueError
                if (
                    not _is_nonnegative_int(patch["left_start"])
                    or not _is_nonnegative_int(patch["left_end"])
                    or patch["left_start"] > patch["left_end"]
                    or not _is_nonnegative_int(patch["right_start"])
                    or not _is_nonnegative_int(patch["right_end"])
                    or patch["right_start"] > patch["right_end"]
                    or not isinstance(patch["left_text"], str)
                    or not isinstance(patch["right_text"], str)
                    or not isinstance(patch["anchor_kind"], str)
                    or not patch["anchor_kind"]
                    or not isinstance(patch["anchor_symbol"], str)
                    or not patch["anchor_symbol"]
                ):
                    raise ValueError
        atoms = tuple(
            DeltaAtom(
                atom_id=row["atom_id"],
                kind=row["kind"],
                patches=tuple(DeltaPatch(**patch) for patch in row["patches"]),
                requires=tuple(row["requires"]),
                affected_functions=tuple(row["affected_functions"]),
                summary=row["summary"],
            )
            for row in payload["atoms"]
        )
        manifest = DeltaManifest(
            schema_version=payload["schema_version"],
            function=payload["function"],
            left_hash=payload["left_hash"],
            right_hash=payload["right_hash"],
            atoms=atoms,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DeltaMinimizeError("corrupt-delta-manifest") from error
    return manifest


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError
        return MappingProxyType({key: _freeze_json(item) for key, item in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError


def _validate_target_descriptor(payload: object, *, original_ig: int) -> None:
    if payload is None:
        return
    if not isinstance(payload, Mapping) or set(payload) != {
        "ig_idx",
        "first_def_sig",
        "use_site_multiset",
        "is_param",
        "var_name",
        "var_confidence",
        "assigned_reg",
        "live_range",
        "use_count",
        "spilled",
    }:
        raise ValueError
    if (
        not _is_nonnegative_int(payload["ig_idx"])
        or payload["ig_idx"] != original_ig
        or not isinstance(payload["first_def_sig"], str)
        or not isinstance(payload["is_param"], bool)
        or payload["var_name"] is not None
        and (not isinstance(payload["var_name"], str) or not payload["var_name"])
        or payload["var_confidence"] is not None
        and (not isinstance(payload["var_confidence"], str) or not payload["var_confidence"])
        or payload["assigned_reg"] is not None
        and (not _is_nonnegative_int(payload["assigned_reg"]) or payload["assigned_reg"] > 31)
        or not _is_nonnegative_int(payload["use_count"])
        or not isinstance(payload["spilled"], bool)
    ):
        raise ValueError
    live_range = payload["live_range"]
    if (
        not isinstance(live_range, (list, tuple))
        or len(live_range) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in live_range)
        or not (tuple(live_range) == (-1, -1) or 0 <= live_range[0] <= live_range[1])
    ):
        raise ValueError
    uses = payload["use_site_multiset"]
    if not isinstance(uses, (list, tuple)):
        raise ValueError
    for item in uses:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or not _is_nonnegative_int(item[1])
        ):
            raise ValueError


def _validate_target_provenance(payload: object) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError
    if set(payload) == {"inference", "parent"}:
        if payload["inference"] != "parent-register-diff" or payload["parent"] not in {"left", "right"}:
            raise ValueError
        return
    if set(payload) == {"schema_version", "baseline_dump"}:
        if (
            payload["schema_version"] != COLOR_TARGET_SCHEMA
            or not isinstance(payload["baseline_dump"], str)
            or not payload["baseline_dump"]
        ):
            raise ValueError
        return
    raise ValueError


def _validate_target_spec(
    payload: object,
    *,
    function: str,
    class_id: int,
    desired_phys: Mapping[int, int],
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "function",
        "target_kind",
        "target_coverage",
        "causal_closure",
        "provenance",
        "roles",
    }:
        raise ValueError
    coverage = payload["target_coverage"]
    if (
        payload["function"] != function
        or payload["target_kind"] != "force_proof_proxy"
        or not isinstance(coverage, float)
        or not math.isfinite(coverage)
        or not 0 <= coverage <= 1
        or not isinstance(payload["causal_closure"], bool)
        or not isinstance(payload["provenance"], Mapping)
        or not isinstance(payload["roles"], (list, tuple))
        or not payload["roles"]
    ):
        raise ValueError
    _validate_target_provenance(payload["provenance"])
    role_phys: dict[int, int] = {}
    ranked_roles: set[int] = set()
    for role in payload["roles"]:
        if not isinstance(role, Mapping) or set(role) != {
            "original_ig",
            "desired_phys",
            "class_id",
            "descriptor",
            "role_order_rank",
        }:
            raise ValueError
        original = role["original_ig"]
        physical = role["desired_phys"]
        rank = role["role_order_rank"]
        if (
            not _is_nonnegative_int(original)
            or not _is_nonnegative_int(physical)
            or physical > 31
            or role["class_id"] != class_id
            or isinstance(role["class_id"], bool)
            or rank is not None
            and not _is_nonnegative_int(rank)
            or original in role_phys
            or rank is not None
            and rank in ranked_roles
        ):
            raise ValueError
        _validate_target_descriptor(role["descriptor"], original_ig=original)
        role_phys[original] = physical
        if rank is not None:
            ranked_roles.add(rank)
    if role_phys != dict(desired_phys):
        raise ValueError
    return _freeze_json(payload)


def _objective_from_dict(payload: Mapping[str, Any], *, function: str) -> ObjectiveManifest:
    try:
        if set(payload) != _OBJECTIVE_FIELDS:
            raise ValueError
        if (
            payload["schema_version"] != OBJECTIVE_MANIFEST_SCHEMA
            or payload["function"] != function
            or payload["class_id"] not in _REGISTER_CLASSES
            or isinstance(payload["class_id"], bool)
            or not isinstance(payload["desired_phys"], Mapping)
            or not payload["desired_phys"]
            or not isinstance(payload["references"], Mapping)
            or set(payload["references"]) != _OBJECTIVE_AXES
        ):
            raise ValueError
        desired: dict[int, int] = {}
        for role, physical in payload["desired_phys"].items():
            if (
                not isinstance(role, str)
                or not role.isdecimal()
                or str(int(role)) != role
                or not _is_nonnegative_int(physical)
                or physical > 31
                or int(role) in desired
            ):
                raise ValueError
            desired[int(role)] = physical
        color_donor = payload["color_donor"]
        objobject_donor = payload["objobject_donor"]
        stack_donor = payload["stack_home_donor"]
        if (
            color_donor not in {None, "left", "right"}
            or objobject_donor not in {"left", "right"}
            or stack_donor not in {None, "left", "right"}
        ):
            raise ValueError
        references: dict[str, AxisReference] = {}
        for axis, row in payload["references"].items():
            if (
                not isinstance(row, Mapping)
                or set(row) != _REFERENCE_FIELDS
                or not isinstance(row["reference_kind"], str)
                or not isinstance(row["reference_artifact"], str)
                or not row["reference_artifact"]
                or row["donor"] not in {None, "left", "right"}
                or not isinstance(row["inference_reason"], str)
                or not row["inference_reason"]
                or not isinstance(row["override"], bool)
                or not isinstance(row["unresolved"], (list, tuple))
                or any(not isinstance(item, str) or not item for item in row["unresolved"])
            ):
                raise ValueError
            references[axis] = AxisReference(
                reference_kind=row["reference_kind"],
                reference_artifact=row["reference_artifact"],
                donor=row["donor"],
                inference_reason=row["inference_reason"],
                override=row["override"],
                unresolved=tuple(row["unresolved"]),
            )
        if (
            references["opcode"].reference_kind != "absolute"
            or references["opcode"].unresolved
            or references["color"].reference_kind != "mixed"
            or references["color"].unresolved
            or references["objobjects"].reference_kind != "proxy"
            or references["objobjects"].unresolved
            or references["stack-homes"].reference_kind not in {"absolute", "mixed"}
            or references["color"].donor != color_donor
            or references["objobjects"].donor != objobject_donor
            or references["stack-homes"].donor != stack_donor
            or references["opcode"].override
            or color_donor is None
            and references["color"].override
            or stack_donor is None
            and references["stack-homes"].override
            or references["stack-homes"].reference_kind == "absolute"
            and references["stack-homes"].unresolved
            or references["stack-homes"].reference_kind == "mixed"
            and (not references["stack-homes"].unresolved or references["stack-homes"].donor is None)
        ):
            raise ValueError
        target_spec = _validate_target_spec(
            payload["target_spec"],
            function=function,
            class_id=payload["class_id"],
            desired_phys=desired,
        )
        objective = ObjectiveManifest(
            schema_version=payload["schema_version"],
            function=payload["function"],
            class_id=payload["class_id"],
            target_spec=target_spec,
            desired_phys=MappingProxyType(dict(sorted(desired.items()))),
            color_donor=color_donor,
            objobject_donor=objobject_donor,
            stack_home_donor=stack_donor,
            references=MappingProxyType(dict(sorted(references.items()))),
        )
        if objective.to_dict() != payload:
            raise ValueError
        return objective
    except (KeyError, TypeError, ValueError) as error:
        raise DeltaMinimizeError("corrupt-objective-manifest") from error


def _validate_objective_donor_context(
    objective: ObjectiveManifest,
    donor_overrides: Mapping[str, str],
) -> None:
    """Bind cached donor semantics to the objective-input context.

    The manifest digest proves integrity, but only this check proves that its
    donor selections, override flags, and inference explanations could have
    been emitted for the bound command inputs.
    """
    try:
        overrides = _canonical_donor_overrides(donor_overrides)
        references = objective.references
        opcode = references["opcode"]
        color = references["color"]
        objobjects = references["objobjects"]
        stack = references["stack-homes"]

        opcode_reasons = {
            None: "expected-assembly-absolute;equal-parent-distance",
            "left": "expected-assembly-absolute;left-parent-closer",
            "right": "expected-assembly-absolute;right-parent-closer",
        }
        if opcode.override or opcode.inference_reason != opcode_reasons[opcode.donor]:
            raise ValueError

        provenance = objective.target_spec["provenance"]
        target_reason = (
            "cross-parent-round-trip-derived-target" if "inference" in provenance else "explicit-versioned-color-target"
        )
        color_override = overrides.get("color")
        if color_override is not None:
            color_reason = "explicit-color-donor-override"
            if objective.color_donor != color_override:
                raise ValueError
        elif objective.color_donor is None:
            color_reason = "equal-assignment-distance-identical-secondary-profiles"
        else:
            color_reason = "lower-desired-assignment-distance"
        if (
            color.override != (color_override is not None)
            or color.inference_reason != f"{target_reason};{color_reason}"
        ):
            raise ValueError

        objobject_override = overrides.get("objobjects")
        if objobject_override is not None:
            expected_objobject_donor = objobject_override
            objobject_reason = "explicit-objobject-donor-override"
        else:
            if objective.color_donor is None:
                raise ValueError
            expected_objobject_donor = objective.color_donor
            objobject_reason = "inherits-selected-color-donor"
        if (
            objective.objobject_donor != expected_objobject_donor
            or objobjects.override != (objobject_override is not None)
            or objobjects.inference_reason != objobject_reason
        ):
            raise ValueError

        stack_override = overrides.get("stack-homes")
        if stack_override is not None:
            stack_reason = "explicit-stack-home-donor-override"
            if objective.stack_home_donor != stack_override:
                raise ValueError
        elif objective.stack_home_donor is None:
            if stack.reference_kind != "absolute":
                raise ValueError
            stack_reason = "equal-absolute-stack-home-distance"
        else:
            stack_reason = "strictly-lower-stack-home-distance"
        if stack.override != (stack_override is not None) or stack.inference_reason != stack_reason:
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise DeltaMinimizeError("corrupt-objective-manifest") from error


def _load_json(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DeltaMinimizeError("corrupt-phase-ledger", {"path": str(path)}) from error
    if not isinstance(value, Mapping):
        raise DeltaMinimizeError("corrupt-phase-ledger", {"path": str(path)})
    return value


def _parent_candidate(side: str, source: str, store: DeltaRunStore) -> MaterializedCandidate:
    path = store.put_source(source)
    return MaterializedCandidate(
        candidate_id=f"parent-{side}",
        mask=0 if side == "left" else 1,
        source_hash=_hash_text(source),
        source_path=path,
        applied_atom_ids=(),
    )


def _capture_parents(
    config: DeltaMinimizeConfig,
    store: DeltaRunStore,
    active: DeltaMinimizeBackends,
    left_source: str,
    right_source: str,
) -> tuple[ParentEvidenceBundle, dict[str, int]]:
    provenance = dict(active.parent_provenance(config))
    required = {
        "cflags_hash",
        "compiler_fingerprint",
        "expected_object_hash",
        "parser_schema_hash",
        "inspector_version",
    }
    if set(provenance) != required or any(type(value) is not str or not value for value in provenance.values()):
        raise DeltaMinimizeError("invalid-parent-evidence-provenance")
    raws: dict[str, RawCandidateEvidence] = {}
    stats = {"parent_hits": 0, "parent_misses": 0}
    for side, source in (("left", left_source), ("right", right_source)):
        candidate = _parent_candidate(side, source, store)
        key = store.parent_evidence_key(candidate, config, provenance)
        cached = store.load_parent_evidence(key)
        if cached is not None:
            try:
                cached_raw = RawCandidateEvidence.from_dict(cached)
                reusable = _validate_cached_artifacts(
                    cached_raw,
                    candidate.source_path,
                    candidate.source_hash,
                    include_objobjects=config.include_objobjects,
                    require_checkdiff=False,
                )
            except DeltaMinimizeError:
                reusable = False
            if not reusable:
                store.invalidate_parent_evidence(key)
                cached = None
        if cached is None:
            raw = active.capture_parent(candidate, config, store)
            if (
                not isinstance(raw, RawCandidateEvidence)
                or raw.candidate_id != candidate.candidate_id
                or raw.source_hash != candidate.source_hash
                or raw.source_path != str(candidate.source_path)
                or not raw.viable
            ):
                raise DeltaMinimizeError("invalid-parent-evidence")
            store.write_parent_evidence(key, raw.to_dict())
            stats["parent_misses"] += 1
        else:
            raw = RawCandidateEvidence.from_dict(cached)
            if (
                raw.candidate_id != candidate.candidate_id
                or raw.source_hash != candidate.source_hash
                or raw.source_path != str(candidate.source_path)
                or not raw.viable
            ):
                raise DeltaMinimizeError("corrupt-cached-evidence")
            stats["parent_hits"] += 1
        raws[side] = raw
    bundle = ParentEvidenceBundle(
        left=raws["left"],
        right=raws["right"],
        cflags_hash=provenance["cflags_hash"],
        compiler_fingerprint=provenance["compiler_fingerprint"],
        expected_object_hash=provenance["expected_object_hash"],
        parser_schema_hash=provenance["parser_schema_hash"],
        inspector_version=provenance["inspector_version"],
    )
    return bundle, stats


def _parent_objective_context(raw: RawCandidateEvidence) -> dict[str, Any]:
    if raw.pcdump_path is None or raw.pcdump_hash is None:
        raise DeltaMinimizeError("invalid-parent-evidence")
    payload = raw.to_dict()
    return {
        "candidate_id": raw.candidate_id,
        "source_path": str(Path(raw.source_path).absolute()),
        "source_hash": raw.source_hash,
        "pcdump_path": str(Path(raw.pcdump_path).absolute()),
        "pcdump_hash": raw.pcdump_hash,
        "checkdiff_digest": (None if raw.checkdiff_evidence is None else _hash_json(raw.checkdiff_evidence)),
        "inspect_digest": None if raw.inspect_text is None else _hash_text(raw.inspect_text),
        "inspection_mode": raw.inspection_mode,
        "evidence_digest": _hash_json(payload),
    }


def _objective_context(config: DeltaMinimizeConfig, parents: ParentEvidenceBundle) -> dict[str, Any]:
    target_hash = None
    if config.target_path is not None:
        try:
            target_hash = hashlib.sha256(config.target_path.read_bytes()).hexdigest()
        except OSError as error:
            raise DeltaMinimizeError("invalid-color-target-path") from error
    return {
        "function": config.function,
        "parents": {
            "left": _parent_objective_context(parents.left),
            "right": _parent_objective_context(parents.right),
        },
        "cflags_from": str(config.cflags_from.absolute()),
        "cflags_hash": parents.cflags_hash,
        "compiler_fingerprint": parents.compiler_fingerprint,
        "expected_object_hash": parents.expected_object_hash,
        "parser_schema_hash": parents.parser_schema_hash,
        "inspector_version": parents.inspector_version,
        "inspector_mode": "objobjects" if config.include_objobjects else "no-objobjects",
        "target": {
            "path": None if config.target_path is None else str(config.target_path.absolute()),
            "content_hash": target_hash,
        },
        "donor_overrides": dict(sorted(config.donor_overrides.items())),
    }


def _objective_context_envelope(
    context: Mapping[str, Any],
    objective_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _json_value(context)
    return {
        "schema_version": OBJECTIVE_INPUTS_SCHEMA,
        "context": normalized,
        "context_digest": _hash_json(normalized),
        "objective_manifest_digest": _hash_json(objective_manifest),
    }


def _load_objective_context(
    path: Path,
    *,
    objective_manifest: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    try:
        payload = _load_json(path)
    except DeltaMinimizeError as error:
        raise DeltaMinimizeError("corrupt-objective-cache-context") from error
    if payload is None:
        return None
    try:
        if set(payload) != {
            "schema_version",
            "context",
            "context_digest",
            "objective_manifest_digest",
        }:
            raise ValueError
        if payload["schema_version"] != OBJECTIVE_INPUTS_SCHEMA:
            raise ValueError
        context = payload["context"]
        digest = payload["context_digest"]
        objective_digest = payload["objective_manifest_digest"]
        if (
            not isinstance(context, Mapping)
            or not _is_digest(digest)
            or _hash_json(context) != digest
            or objective_manifest is None
            or not _is_digest(objective_digest)
            or _hash_json(objective_manifest) != objective_digest
        ):
            raise ValueError
        return _json_value(context)
    except (KeyError, TypeError, ValueError) as error:
        raise DeltaMinimizeError("corrupt-objective-cache-context") from error


def _load_or_infer_objective(
    config: DeltaMinimizeConfig,
    parents: ParentEvidenceBundle,
    store: DeltaRunStore,
    active: DeltaMinimizeBackends,
) -> ObjectiveManifest:
    context = _objective_context(config, parents)
    old_manifest = _load_json(store.root / "objective-manifest.json")
    old_context = _load_objective_context(
        store.root / "objective-inputs.json",
        objective_manifest=old_manifest,
    )
    if (old_context is None) != (old_manifest is None):
        raise DeltaMinimizeError("corrupt-objective-cache-context")
    if old_context == context and old_manifest is not None:
        objective = _objective_from_dict(old_manifest, function=config.function)
        _validate_objective_donor_context(objective, config.donor_overrides)
        try:
            expected = _infer_validated_objective(config, parents, active)
        except DeltaMinimizeError as error:
            raise DeltaMinimizeError("corrupt-objective-manifest") from error
        if objective.to_dict() != expected.to_dict():
            raise DeltaMinimizeError("corrupt-objective-manifest")
    else:
        try:
            objective = _infer_validated_objective(config, parents, active)
        except DeltaMinimizeError as error:
            if error.reason in {
                "ambiguous-color-target",
                "ambiguous-color-donor",
                "ambiguous-objobject-donor",
                "ambiguous-stack-home-donor",
            }:
                raise
            raise DeltaMinimizeError("invalid-objective-manifest") from error
        objective_payload = objective.to_dict()
        store.write_objective_manifest(objective_payload)
        store.write_json(
            "objective-inputs.json",
            _objective_context_envelope(context, objective_payload),
        )
    return objective


def _infer_validated_objective(
    config: DeltaMinimizeConfig,
    parents: ParentEvidenceBundle,
    active: DeltaMinimizeBackends,
) -> ObjectiveManifest:
    """Derive the one canonical manifest permitted by current parent evidence.

    Parent capture artifacts are already content-validated before this point,
    so this repeats only deterministic profiling/inference.  Reusing a cache
    entry therefore cannot make its semantically meaningful strings, target
    fields, or donors authoritative merely by recomputing its JSON digest.
    """
    left = active.parent_objective(parents.left, "left", config)
    right = active.parent_objective(parents.right, "right", config)
    objective = active.infer_objective(left, right, config)
    if not isinstance(objective, ObjectiveManifest) or objective.function != config.function:
        raise DeltaMinimizeError("invalid-objective-manifest")
    objective = _objective_from_dict(objective.to_dict(), function=config.function)
    _validate_objective_donor_context(objective, config.donor_overrides)
    return objective


def _load_or_extract_manifest(
    config: DeltaMinimizeConfig,
    store: DeltaRunStore,
    active: DeltaMinimizeBackends,
    left_source: str,
    right_source: str,
) -> DeltaManifest:
    manifest = active.extract_manifest(left_source, right_source, function=config.function)
    if not isinstance(manifest, DeltaManifest):
        raise DeltaMinimizeError("invalid-delta-manifest")
    try:
        canonical = _manifest_from_dict(_manifest_to_dict(manifest))
    except DeltaMinimizeError as error:
        raise DeltaMinimizeError("invalid-delta-manifest") from error
    left_hash = _hash_text(left_source)
    right_hash = _hash_text(right_source)
    if canonical.function != config.function or canonical.left_hash != left_hash or canonical.right_hash != right_hash:
        raise DeltaMinimizeError("invalid-delta-manifest")

    old = _load_json(store.root / "delta-manifest.json")
    if old is None:
        store.write_delta_manifest(_manifest_to_dict(canonical))
        return canonical

    cached = _manifest_from_dict(old)
    if cached.function != config.function or cached.left_hash != left_hash or cached.right_hash != right_hash:
        store.write_delta_manifest(_manifest_to_dict(canonical))
        return canonical
    if _manifest_to_dict(cached) != _manifest_to_dict(canonical):
        raise DeltaMinimizeError("corrupt-delta-manifest")
    return canonical


def _changed_bytes(first: str, second: str) -> int:
    return sum(left != right for left, right in zip_longest(first.encode(), second.encode(), fillvalue=None))


def _materialize_candidates(
    left: str,
    right: str,
    manifest: DeltaManifest,
    masks: tuple[int, ...],
    store: DeltaRunStore,
) -> tuple[MaterializedCandidate, ...]:
    width = max(1, len(manifest.atoms))
    out: list[MaterializedCandidate] = []
    for mask in masks:
        source = materialize_mask(left, manifest, mask)
        full = (1 << len(manifest.atoms)) - 1
        if (mask == 0 and source != left) or (mask == full and source != right):
            raise DeltaMinimizeError("endpoint-reproduction-failed")
        out.append(
            MaterializedCandidate(
                candidate_id=f"mask-{mask:0{width}b}",
                mask=mask,
                source_hash=_hash_text(source),
                source_path=store.put_source(source),
                applied_atom_ids=tuple(
                    atom.atom_id for index, atom in enumerate(manifest.atoms) if mask & (1 << index)
                ),
            )
        )
    return tuple(out)


def _candidate_row(
    candidate: MaterializedCandidate,
    raw: RawCandidateEvidence,
    profile: CandidateProfile,
    *,
    atom_count: int,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "mask": candidate.mask,
        "applied_atoms": list(candidate.applied_atom_ids),
        "distance_from_left": candidate.mask.bit_count(),
        "distance_from_right": atom_count - candidate.mask.bit_count(),
        "source_hash": candidate.source_hash,
        "source_path": str(candidate.source_path),
        "evidence": raw.to_dict(),
        "profile": profile.to_dict(),
    }


def _provisional_summary(pareto: ParetoSummary) -> ParetoSummary:
    return replace(
        pareto,
        status="provisional",
        joint_solutions=(),
        joint_zero_all_candidate_ids=(),
    )


def _build_result(
    config: DeltaMinimizeConfig,
    objective: ObjectiveManifest,
    manifest: DeltaManifest,
    rows: list[Mapping[str, Any]],
    profiles: list[CandidateProfile],
    cache_stats: Mapping[str, int],
    compiler_provenance: Mapping[str, str],
    *,
    pareto: ParetoSummary | None,
    blockers: tuple[str, ...] = (),
    legal_count: int | None = None,
) -> DeltaMinimizeResult:
    if pareto is None:
        status = "incomplete"
        exact = False
        best_next = None
    elif config.include_objobjects:
        status = pareto.status
        exact = True
        best_next = pareto.best_next
    else:
        pareto = _provisional_summary(pareto)
        status = "provisional"
        exact = False
        best_next = pareto.best_next
    return DeltaMinimizeResult(
        schema_version=RESULT_SCHEMA,
        status=status,
        exact_four_axis=exact,
        function=config.function,
        objective_manifest=objective.to_dict(),
        delta_manifest=_manifest_to_dict(manifest),
        candidate_counts={
            "legal": len(rows) if legal_count is None else legal_count,
            "viable": sum(profile.viable for profile in profiles),
            "complete": sum(profile.viable and profile.complete for profile in profiles),
        },
        candidates=tuple(rows),
        pareto=pareto,
        best_next=best_next,
        cache_stats=cache_stats,
        blockers=blockers,
        inputs={
            "left": str(config.left),
            "right": str(config.right),
            "left_hash": manifest.left_hash,
            "right_hash": manifest.right_hash,
            "out_dir": str(config.out_dir),
            "target_path": None if config.target_path is None else str(config.target_path),
            "donor_overrides": dict(config.donor_overrides),
            "include_objobjects": config.include_objobjects,
        },
        compiler_provenance=compiler_provenance,
        candidate_budget=config.max_candidates,
    )


def run_delta_minimize(
    config: DeltaMinimizeConfig,
    *,
    backends: DeltaMinimizeBackends | None = None,
) -> DeltaMinimizeResult:
    """Run every legal parent-delta mask and publish only a complete frontier."""

    if not isinstance(config, DeltaMinimizeConfig):
        raise DeltaMinimizeError("invalid-delta-minimize-config")
    active = backends or default_delta_minimize_backends()
    store = DeltaRunStore(config.out_dir)
    left_source = _read_source(config.left, side="left")
    right_source = _read_source(config.right, side="right")

    try:
        parents, _parent_cache_activity = _capture_parents(config, store, active, left_source, right_source)
    except DeltaMinimizeError as error:
        if error.reason not in {"parent-score-infrastructure", "inspector-timeout", "inspector-failed"}:
            raise
        result = DeltaMinimizeResult(
            schema_version=RESULT_SCHEMA,
            status="incomplete",
            exact_four_axis=False,
            function=config.function,
            objective_manifest={},
            delta_manifest={},
            candidate_counts={"legal": 0, "viable": 0, "complete": 0},
            candidates=(),
            pareto=None,
            best_next=None,
            cache_stats={"parent_entries": 0, "candidate_entries": 0},
            blockers=(error.reason,),
            inputs={
                "left": str(config.left),
                "right": str(config.right),
                "left_hash": _hash_text(left_source),
                "right_hash": _hash_text(right_source),
                "out_dir": str(config.out_dir),
                "target_path": None if config.target_path is None else str(config.target_path),
                "donor_overrides": dict(config.donor_overrides),
                "include_objobjects": config.include_objobjects,
            },
            compiler_provenance={},
            candidate_budget=config.max_candidates,
        )
        store.write_result(result.to_dict())
        return result
    objective = _load_or_infer_objective(config, parents, store, active)
    objective_hash = _hash_json(objective.to_dict())
    store.bind_provenance(
        {
            "cflags_hash": parents.cflags_hash,
            "compiler_fingerprint": parents.compiler_fingerprint,
            "expected_object_hash": parents.expected_object_hash,
            "objective_manifest_hash": objective_hash,
            "parser_schema_hash": parents.parser_schema_hash,
            "inspector_version": parents.inspector_version,
        }
    )
    manifest = _load_or_extract_manifest(config, store, active, left_source, right_source)
    masks = enumerate_legal_masks(manifest, max_candidates=config.max_candidates)
    candidates = _materialize_candidates(left_source, right_source, manifest, masks, store)
    store.write_color_target(objective.target_spec)
    target = store.write_score_target(objective.function, objective.desired_phys)
    evaluation = CandidateEvaluationConfig(
        melee_root=config.melee_root,
        function=config.function,
        cflags_from=config.cflags_from,
        target_path=target,
        output_dir=config.out_dir / "candidates",
        include_objobjects=config.include_objobjects,
    )

    rows: list[Mapping[str, Any]] = []
    profiles: list[CandidateProfile] = []
    for candidate in candidates:
        try:
            raw = capture_candidate(candidate, evaluation, backends=active.evaluation, store=store)
            profile = active.profile_candidate(raw, objective, parents=parents)
        except DeltaMinimizeError as error:
            blockers = tuple(
                dict.fromkeys((*[item for profile in profiles for item in profile.blockers], error.reason))
            )
            stats = {"parent_entries": 2, "candidate_entries": len(rows)}
            result = _build_result(
                config,
                objective,
                manifest,
                rows,
                profiles,
                stats,
                {
                    "cflags_hash": parents.cflags_hash,
                    "compiler_fingerprint": parents.compiler_fingerprint,
                    "expected_object_hash": parents.expected_object_hash,
                    "inspector_version": parents.inspector_version,
                    "parser_schema_hash": parents.parser_schema_hash,
                },
                pareto=None,
                blockers=blockers,
                legal_count=len(candidates),
            )
            store.write_candidates({"candidates": list(rows)})
            store.write_result(result.to_dict())
            return result
        source = candidate.source_path.read_text(encoding="utf-8")
        profile = replace(
            profile,
            changed_bytes_from_left=_changed_bytes(left_source, source),
            changed_bytes_from_right=_changed_bytes(right_source, source),
        )
        profiles.append(profile)
        rows.append(_candidate_row(candidate, raw, profile, atom_count=len(manifest.atoms)))
        store.write_candidates({"candidates": list(rows)})

    stats = {"parent_entries": 2, "candidate_entries": len(rows)}
    incomplete = [profile for profile in profiles if profile.viable and not profile.complete]
    if incomplete:
        blockers = tuple(dict.fromkeys(item for profile in incomplete for item in profile.blockers))
        result = _build_result(
            config,
            objective,
            manifest,
            rows,
            profiles,
            stats,
            {
                "cflags_hash": parents.cflags_hash,
                "compiler_fingerprint": parents.compiler_fingerprint,
                "expected_object_hash": parents.expected_object_hash,
                "inspector_version": parents.inspector_version,
                "parser_schema_hash": parents.parser_schema_hash,
            },
            pareto=None,
            blockers=blockers,
            legal_count=len(candidates),
        )
    else:
        pareto = reduce_pareto(profiles, atom_count=len(manifest.atoms))
        result = _build_result(
            config,
            objective,
            manifest,
            rows,
            profiles,
            stats,
            {
                "cflags_hash": parents.cflags_hash,
                "compiler_fingerprint": parents.compiler_fingerprint,
                "expected_object_hash": parents.expected_object_hash,
                "inspector_version": parents.inspector_version,
                "parser_schema_hash": parents.parser_schema_hash,
            },
            pareto=pareto,
            legal_count=len(candidates),
        )
    store.write_result(result.to_dict())
    return result


def default_delta_minimize_backends() -> DeltaMinimizeBackends:
    """Build production adapters lazily so hermetic callers need no toolchain."""

    evaluation = default_evaluation_backends()
    return DeltaMinimizeBackends(
        parent_provenance=_default_parent_provenance,
        capture_parent=lambda candidate, config, store: _default_capture_parent(
            candidate,
            config,
            store,
            evaluation,
        ),
        parent_objective=_default_parent_objective,
        infer_objective=_default_infer_objective,
        evaluation=evaluation,
    )


def _default_parent_provenance(config: DeltaMinimizeConfig) -> Mapping[str, str]:
    """Fingerprint the build unit, compiler configuration, expected object, and inspector."""

    try:
        expected = unit_paths(config.melee_root, config.cflags_from).ref_obj
    except (OSError, ValueError) as error:
        raise DeltaMinimizeError("missing-expected-object") from error
    if expected.is_symlink() or not expected.is_file():
        raise DeltaMinimizeError("missing-expected-object", {"path": str(expected)})
    try:
        expected_hash = _file_hash(expected)
        unit_bytes = config.cflags_from.read_bytes()
    except (OSError, ValueError) as error:
        raise DeltaMinimizeError("invalid-compiler-context") from error

    build_identity = hashlib.sha256()
    build_identity.update(str(config.cflags_from.absolute()).encode())
    build_identity.update(b"\0")
    build_identity.update(unit_bytes)
    compiler_identity = hashlib.sha256(b"mwcc_233_163n\0")
    for relative in ("config/GALE01/config.yml", "configure.py"):
        path = config.melee_root / relative
        if path.is_file() and not path.is_symlink():
            compiler_identity.update(relative.encode())
            compiler_identity.update(b"\0")
            compiler_identity.update(path.read_bytes())
    inspector_source = Path(__file__).parents[2] / "mwcc_debug" / "diff_capture.py"
    inspector_digest = hashlib.sha256(
        inspector_source.read_bytes() if inspector_source.is_file() else b"mwcc-inspect"
    ).hexdigest()
    return {
        "cflags_hash": build_identity.hexdigest(),
        "compiler_fingerprint": f"mwcc_233_163n:{compiler_identity.hexdigest()}",
        "expected_object_hash": expected_hash,
        "parser_schema_hash": PARSER_SCHEMA_HASH,
        "inspector_version": f"mwcc-inspect:{inspector_digest}",
    }


def _default_capture_parent(
    candidate: MaterializedCandidate,
    config: DeltaMinimizeConfig,
    store: DeltaRunStore,
    evaluation: EvaluationBackends,
) -> RawCandidateEvidence:
    score_config = ScoreSourceConfig(
        repo_root=config.melee_root,
        function=config.function,
        target=None,
        cflags_from=config.cflags_from,
        expression_source=config.cflags_from,
        expression_baseline=None,
        expression_reg_class="gpr",
        output_dir=config.out_dir / "parents",
        timeout=120.0,
        checkdiff_guard=True,
        full_unit_source=True,
    )
    rows = evaluation.score_rows(
        [
            {
                "candidate_id": candidate.candidate_id,
                "source_file": str(candidate.source_path),
                "source_retained": str(candidate.source_path),
                "full_unit_source": True,
            }
        ],
        score_config,
    )
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise DeltaMinimizeError("malformed-parent-score-result")
    row = rows[0]
    if row.get("score_error_kind") == "infrastructure":
        raise DeltaMinimizeError("parent-score-infrastructure", {"side": candidate.candidate_id})
    if _compile_rejected(row) or row.get("score_error_kind") == "candidate":
        raise DeltaMinimizeError("invalid-parent-source", {"side": candidate.candidate_id})
    pcdump = row.get("pcdump_path")
    checkdiff = row.get("checkdiff_evidence")
    if not isinstance(pcdump, str) or not pcdump or not isinstance(checkdiff, Mapping):
        raise DeltaMinimizeError("incomplete-parent-evidence", {"side": candidate.candidate_id})
    try:
        pcdump_hash = _file_hash(Path(pcdump))
    except (OSError, ValueError) as error:
        raise DeltaMinimizeError("incomplete-parent-evidence", {"side": candidate.candidate_id}) from error
    evidence = RawCandidateEvidence(
        candidate_id=candidate.candidate_id,
        mask=candidate.mask,
        source_path=str(candidate.source_path),
        source_hash=candidate.source_hash,
        compile_status="compiled",
        viable=True,
        pcdump_path=pcdump,
        checkdiff_evidence=checkdiff,
        inspect_text=None,
        compiler_stderr=_compile_diagnostics(row),
        blockers=_candidate_blockers(row),
        inspection_mode="objobjects" if config.include_objobjects else "no-objobjects",
        pcdump_hash=pcdump_hash,
    )
    if config.include_objobjects:
        try:
            inspect_text = _invoke_inspector(
                evaluation.inspect_source,
                candidate.source_path,
                config.function,
                store.inspect_output_path(candidate.candidate_id),
                180,
                config.melee_root,
            )
        except (subprocess.TimeoutExpired, TimeoutError) as error:
            raise DeltaMinimizeError("inspector-timeout", {"candidate_id": candidate.candidate_id}) from error
        except DeltaMinimizeError:
            raise
        except Exception as error:
            raise DeltaMinimizeError("inspector-failed", {"candidate_id": candidate.candidate_id}) from error
        evidence = RawCandidateEvidence(
            **{**evidence.to_dict(), "blockers": evidence.blockers, "inspect_text": inspect_text}
        )
    return evidence


def _expected_stack_profile(
    payload: Mapping[str, Any],
    function: str,
    inputs: tuple[Mapping[str, Any], Mapping[str, Any] | None] | None = None,
):
    frame, stack = inputs or _frame_and_stack(payload, function)
    expected_frame, expected_stack = deepcopy((frame, stack))
    raw_expected = expected_frame.get("expected")
    expected_size = raw_expected.get("frame_size") if isinstance(raw_expected, Mapping) else None
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        classification = payload.get("classification")
        sizes = classification.get("stack_frame_sizes") if isinstance(classification, Mapping) else None
        expected_size = sizes.get("expected_frame_size") if isinstance(sizes, Mapping) else None
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise DeltaMinimizeError("incomplete-parent-stack-evidence")
    current = expected_frame.get("current")
    if not isinstance(current, dict):
        raise DeltaMinimizeError("incomplete-parent-stack-evidence")
    current["frame_size"] = expected_size
    assignments = current.get("stack_home_assignments")
    if isinstance(assignments, list):
        for assignment in assignments:
            if isinstance(assignment, dict) and isinstance(assignment.get("expected_offset"), int):
                assignment["offset"] = assignment["expected_offset"]
    if isinstance(expected_stack, dict):
        candidates = expected_stack.get("candidates")
        if isinstance(candidates, list):
            for row in candidates:
                if not isinstance(row, dict):
                    continue
                mismatch = row.get("mismatch")
                expected_offset = row.get("expected_offset")
                if not isinstance(expected_offset, int) and isinstance(mismatch, Mapping):
                    expected_offset = mismatch.get("expected_offset")
                if isinstance(expected_offset, int) and not isinstance(expected_offset, bool):
                    row["current_offset"] = expected_offset
                    if isinstance(mismatch, dict):
                        mismatch["current_offset"] = expected_offset
    profile = build_stack_home_profile(expected_frame, expected_stack)
    if not profile.complete:
        raise DeltaMinimizeError("incomplete-parent-stack-evidence")
    return profile


def _validated_asm_lines(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(line, str) for line in value):
        raise ValueError("invalid assembly evidence")
    lines = tuple(line for line in value if line.strip())
    if not lines:
        raise ValueError("empty assembly evidence")
    return lines


def _default_parent_objective(
    raw: RawCandidateEvidence,
    side: str,
    config: DeltaMinimizeConfig,
) -> ParentObjectiveEvidence:
    payload = raw.checkdiff_evidence
    if raw.pcdump_path is None or payload is None:
        raise DeltaMinimizeError("incomplete-parent-evidence", {"side": side})
    try:
        target_asm = _validated_asm_lines(payload.get("target_asm"))
        current_asm = _validated_asm_lines(payload.get("current_asm"))
    except ValueError:
        raise DeltaMinimizeError("incomplete-parent-opcode-evidence")
    try:
        source = Path(raw.source_path).read_text(encoding="utf-8")
        compile = role_descriptor.Compile.from_text(
            Path(raw.pcdump_path).read_text(encoding="utf-8"),
            config.function,
            source,
        )
        opcode_distance = opcode_graph_distance(
            parse_opcode_graph(list(target_asm)),
            parse_opcode_graph(list(current_asm)),
            structural_status=_structural_status(payload),
        )
        stack_inputs = _evidence_frame_and_stack(raw, config.function)
        stack_profile = build_stack_home_profile(*stack_inputs)
        absolute_stack = _expected_stack_profile(payload, config.function, stack_inputs)
        stack_distance = stack_home_distance(stack_profile, absolute_stack).as_tuple()
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        raise DeltaMinimizeError("incomplete-parent-evidence", {"side": side}) from error
    if not stack_profile.complete:
        raise DeltaMinimizeError("incomplete-parent-stack-evidence", {"side": side})
    if config.include_objobjects:
        if raw.inspect_text is None:
            raise DeltaMinimizeError("incomplete-parent-objobject-evidence", {"side": side})
        objobjects = parse_objobject_profile(raw.inspect_text, config.function)
    else:
        objobjects = ObjObjectProfile((), True)
    class_id = 0
    if config.target_path is not None:
        class_id = load_color_target(config.target_path, function=config.function).class_id
    else:
        raw_class = payload.get("color_class_id", payload.get("class_id", 0))
        if isinstance(raw_class, int) and not isinstance(raw_class, bool) and raw_class in {0, 1}:
            class_id = raw_class
    expected_artifact = f"expected-object:{_default_parent_provenance(config)['expected_object_hash']}"
    return ParentObjectiveEvidence(
        side=side,
        function=config.function,
        class_id=class_id,
        compile=compile,
        pcdump_path=Path(raw.pcdump_path),
        expected_assembly=tuple(target_asm),
        current_assembly=tuple(current_asm),
        opcode_distance=opcode_distance,
        color_profile=None,
        objobject_profile=objobjects,
        stack_home_profile=stack_profile,
        stack_absolute_distance=tuple(stack_distance),  # type: ignore[arg-type]
        stack_unresolved=tuple(sorted(home.identity for home in stack_profile.homes if home.reference_kind == "proxy")),
        expected_assembly_artifact=f"{expected_artifact}:{config.function}:assembly",
        pcdump_artifact=raw.pcdump_path,
        objobject_artifact=f"{config.out_dir}/evidence/{raw.candidate_id}/inspect.txt",
        stack_absolute_artifact=f"{expected_artifact}:{config.function}:stack",
        stack_profile_artifact=f"{raw.pcdump_path}:stack-profile",
    )


def _default_infer_objective(left: Any, right: Any, config: DeltaMinimizeConfig) -> ObjectiveManifest:
    from ...cli.debug import _derive_force_phys_from_register_diff_lines

    return infer_objective_manifest(
        left,
        right,
        target_path=config.target_path,
        donor_overrides=config.donor_overrides,
        derive_force_target=_derive_force_phys_from_register_diff_lines,
    )
