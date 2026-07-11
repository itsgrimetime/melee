"""Ordered, resumable orchestration for closed-world delta minimization."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from itertools import zip_longest
from pathlib import Path
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
            or not isinstance(self.donor_overrides, Mapping)
            or not isinstance(self.include_objobjects, bool)
        ):
            raise DeltaMinimizeError("invalid-delta-minimize-config")


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
    if manifest.schema_version != "delta-manifest.v1":
        raise DeltaMinimizeError("corrupt-delta-manifest")
    return manifest


def _objective_from_dict(payload: Mapping[str, Any]) -> ObjectiveManifest:
    try:
        references = {
            axis: AxisReference(
                reference_kind=row["reference_kind"],
                reference_artifact=row["reference_artifact"],
                donor=row["donor"],
                inference_reason=row["inference_reason"],
                override=row["override"],
                unresolved=tuple(row["unresolved"]),
            )
            for axis, row in payload["references"].items()
        }
        desired = {int(role): physical for role, physical in payload["desired_phys"].items()}
        return ObjectiveManifest(
            schema_version=payload["schema_version"],
            function=payload["function"],
            class_id=payload["class_id"],
            target_spec=payload["target_spec"],
            desired_phys=desired,
            color_donor=payload["color_donor"],
            objobject_donor=payload["objobject_donor"],
            stack_home_donor=payload["stack_home_donor"],
            references=references,
        )
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
        inspector_version=provenance["inspector_version"],
    )
    return bundle, stats


def _objective_context(config: DeltaMinimizeConfig, parents: ParentEvidenceBundle) -> dict[str, Any]:
    target_hash = None
    if config.target_path is not None:
        try:
            target_hash = hashlib.sha256(config.target_path.read_bytes()).hexdigest()
        except OSError as error:
            raise DeltaMinimizeError("invalid-color-target-path") from error
    return {
        "function": config.function,
        "left_hash": parents.left.source_hash,
        "right_hash": parents.right.source_hash,
        "target_path": None if config.target_path is None else str(config.target_path.absolute()),
        "target_hash": target_hash,
        "donor_overrides": dict(sorted(config.donor_overrides.items())),
        "include_objobjects": config.include_objobjects,
    }


def _load_or_infer_objective(
    config: DeltaMinimizeConfig,
    parents: ParentEvidenceBundle,
    store: DeltaRunStore,
    active: DeltaMinimizeBackends,
) -> ObjectiveManifest:
    context = _objective_context(config, parents)
    old_context = _load_json(store.root / "objective-inputs.json")
    old_manifest = _load_json(store.root / "objective-manifest.json")
    if old_context == context and old_manifest is not None:
        objective = _objective_from_dict(old_manifest)
    else:
        left = active.parent_objective(parents.left, "left", config)
        right = active.parent_objective(parents.right, "right", config)
        objective = active.infer_objective(left, right, config)
        if not isinstance(objective, ObjectiveManifest) or objective.function != config.function:
            raise DeltaMinimizeError("invalid-objective-manifest")
        store.write_objective_manifest(objective.to_dict())
        store.write_json("objective-inputs.json", context)
    return objective


def _load_or_extract_manifest(
    config: DeltaMinimizeConfig,
    store: DeltaRunStore,
    active: DeltaMinimizeBackends,
    left_source: str,
    right_source: str,
) -> DeltaManifest:
    old = _load_json(store.root / "delta-manifest.json")
    if old is not None:
        manifest = _manifest_from_dict(old)
        if (
            manifest.function == config.function
            and manifest.left_hash == _hash_text(left_source)
            and manifest.right_hash == _hash_text(right_source)
        ):
            return manifest
    manifest = active.extract_manifest(left_source, right_source, function=config.function)
    if not isinstance(manifest, DeltaManifest):
        raise DeltaMinimizeError("invalid-delta-manifest")
    store.write_delta_manifest(_manifest_to_dict(manifest))
    return manifest


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
            "parser_schema_hash": PARSER_SCHEMA_HASH,
            "inspector_version": parents.inspector_version,
        }
    )
    manifest = _load_or_extract_manifest(config, store, active, left_source, right_source)
    masks = enumerate_legal_masks(manifest, max_candidates=config.max_candidates)
    candidates = _materialize_candidates(left_source, right_source, manifest, masks, store)
    target = store.write_color_target(objective.target_spec)
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
                    "parser_schema_hash": PARSER_SCHEMA_HASH,
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
                "parser_schema_hash": PARSER_SCHEMA_HASH,
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
                "parser_schema_hash": PARSER_SCHEMA_HASH,
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


def _expected_stack_profile(payload: Mapping[str, Any], function: str):
    frame, stack = _frame_and_stack(payload, function)
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


def _default_parent_objective(
    raw: RawCandidateEvidence,
    side: str,
    config: DeltaMinimizeConfig,
) -> ParentObjectiveEvidence:
    payload = raw.checkdiff_evidence
    if raw.pcdump_path is None or payload is None:
        raise DeltaMinimizeError("incomplete-parent-evidence", {"side": side})
    target_asm = payload.get("target_asm")
    current_asm = payload.get("current_asm")
    if (
        not isinstance(target_asm, (list, tuple))
        or not target_asm
        or any(not isinstance(line, str) or not line for line in target_asm)
        or not isinstance(current_asm, (list, tuple))
        or not current_asm
        or any(not isinstance(line, str) or not line for line in current_asm)
    ):
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
        stack_inputs = _frame_and_stack(payload, config.function)
        stack_profile = build_stack_home_profile(*stack_inputs)
        absolute_stack = _expected_stack_profile(payload, config.function)
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
    return infer_objective_manifest(
        left,
        right,
        target_path=config.target_path,
        donor_overrides=config.donor_overrides,
    )
