from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import compare_pressure_signatures, pressure_signature_from_pcdump
from .facts import facts_from_pcdump
from .models import (
    AllocatorFacts,
    AllocatorNode,
    CandidateComparison,
    CandidateSpec,
    TargetAllocation,
    TargetSet,
)


def parse_candidate_specs(
    raw_specs: list[str] | None,
    *,
    validate_mode: str,
) -> tuple[CandidateSpec, ...]:
    if not raw_specs:
        return ()

    return tuple(
        _parse_candidate_spec(raw_spec, validate_mode=validate_mode)
        for raw_spec in raw_specs
    )


def _parse_candidate_spec(raw_spec: str, *, validate_mode: str) -> CandidateSpec:
    label, separator, raw_path = raw_spec.partition("=")
    if separator == "" or label.strip() == "" or raw_path.strip() == "":
        raise ValueError("candidate must use LABEL=path")

    path = raw_path.strip()
    if path.endswith(".pcdump.txt") or path.endswith(".txt"):
        kind = "pcdump"
    elif path.endswith(".c"):
        kind = _source_candidate_kind(validate_mode)
    else:
        raise ValueError("candidate must be .pcdump.txt, .txt, or .c")

    return CandidateSpec(label=label.strip(), path=path, kind=kind)


def _source_candidate_kind(validate_mode: str) -> str:
    if validate_mode in {"quick", "bounded"}:
        return "source"
    if validate_mode == "remote":
        return "source-dry-run"
    if validate_mode == "none":
        raise ValueError("source candidate requires compile-capable validation mode")
    raise ValueError(f"unknown validation mode {validate_mode!r}")


def compare_candidate_pcdumps(
    baseline: AllocatorFacts,
    target_set: TargetSet,
    *,
    candidates: list[tuple[str, Path]],
    source_text: str | None = None,
    require_reanchor: bool = False,
    validation_evidence: dict[str, dict[str, object]] | None = None,
) -> tuple[CandidateComparison, ...]:
    return tuple(
        _compare_candidate_pcdump(
            baseline,
            target_set,
            label=label,
            path=path,
            source_text=source_text,
            require_reanchor=require_reanchor,
            validation_evidence=(
                None if validation_evidence is None else validation_evidence.get(label)
            ),
        )
        for label, path in candidates
    )


def _compare_candidate_pcdump(
    baseline: AllocatorFacts,
    target_set: TargetSet,
    *,
    label: str,
    path: Path,
    source_text: str | None,
    require_reanchor: bool,
    validation_evidence: dict[str, object] | None,
) -> CandidateComparison:
    candidate_text = path.read_text()
    function = baseline.function.name
    guard_warnings = _guard_failure_warnings(validation_evidence)

    try:
        candidate = facts_from_pcdump(
            candidate_text,
            function,
            pcdump_path=path,
            source_text=source_text,
            class_filter=tuple(_target_class_ids(target_set)),
        )
    except ValueError as exc:
        if "not found in pcdump" in str(exc):
            return _unsafe_comparison(
                baseline,
                target_set,
                label=label,
                path=path,
                candidate_text=candidate_text,
                identity_status="function_missing",
                warnings=(str(exc), *guard_warnings),
            )
        raise

    if require_reanchor and source_text is None:
        warnings = (
            "role reanchor unavailable for candidate identity check",
            *guard_warnings,
        )
        return _unsafe_comparison(
            baseline,
            target_set,
            label=label,
            path=path,
            candidate_text=candidate_text,
            identity_status="unsafe",
            warnings=warnings,
        )

    reanchor_identity_status = "trusted"
    reanchored_targets: dict[int, TargetAllocation] = {}
    reanchor_unsafe: dict[int, str] = {}
    reanchor_warnings: tuple[str, ...] = ()
    if require_reanchor:
        (
            reanchor_identity_status,
            reanchored_targets,
            reanchor_unsafe,
            reanchor_warnings,
        ) = _reanchor_candidate_targets(
            baseline,
            target_set,
            candidate_text,
            source_text=source_text,
        )

    baseline_classes = baseline.class_by_id()
    candidate_classes = candidate.class_by_id()
    target_results: dict[int, dict[str, Any]] = {}
    reanchored_candidate_ids = False
    for target in target_set.targets:
        baseline_node = baseline_classes.get(target.class_id, None)
        candidate_node = candidate_classes.get(target.class_id, None)
        baseline_by_ig = {} if baseline_node is None else baseline_node.node_by_ig()
        candidate_by_ig = {} if candidate_node is None else candidate_node.node_by_ig()
        if target.ig_id not in baseline_by_ig:
            target_results[target.ig_id] = _unsafe_target_result(
                baseline,
                target,
                warning="baseline target not found",
            )
            continue
        if target.ig_id in reanchor_unsafe:
            target_results[target.ig_id] = _unsafe_target_result(
                baseline,
                target,
                warning=reanchor_unsafe[target.ig_id],
            )
            continue
        effective_target = reanchored_targets.get(target.ig_id, target)
        if effective_target.ig_id != target.ig_id:
            reanchored_candidate_ids = True
        target_results[target.ig_id] = _target_result(
            target,
            baseline_by_ig.get(target.ig_id),
            candidate_by_ig.get(effective_target.ig_id),
            candidate_ig_id=effective_target.ig_id,
        )

    status = (
        "rejected"
        if guard_warnings or reanchor_unsafe
        else _candidate_status(target_results)
    )
    pressure_delta = (
        {
            "status": "unavailable",
            "reason": "pressure delta unavailable for reanchored candidate ids",
        }
        if reanchored_candidate_ids
        else _pressure_delta_dict(
            baseline,
            candidate_text,
            target_set,
            function=function,
        )
    )
    return CandidateComparison(
        label=label,
        path=str(path),
        status=status,
        target_results=target_results,
        pressure_delta=pressure_delta,
        identity_status=reanchor_identity_status,
        warnings=(*guard_warnings, *reanchor_warnings),
    )


def _target_result(
    target: TargetAllocation,
    baseline_node: AllocatorNode | None,
    candidate_node: AllocatorNode | None,
    *,
    candidate_ig_id: int | None = None,
) -> dict[str, Any]:
    baseline_phys = None if baseline_node is None else baseline_node.assigned_phys
    candidate_phys = None if candidate_node is None else candidate_node.assigned_phys
    expected = target.expected_phys
    baseline_distance = _phys_distance(baseline_phys, expected)
    candidate_distance = _phys_distance(candidate_phys, expected)
    baseline_satisfied = baseline_phys == expected
    satisfied = candidate_phys == expected
    unsafe = candidate_node is None
    regressed = (
        unsafe
        or (baseline_satisfied and not satisfied)
        or (
            baseline_distance is not None
            and candidate_distance is not None
            and candidate_distance > baseline_distance
        )
    )
    improved = (
        not unsafe
        and not baseline_satisfied
        and (
            satisfied
            or (
                baseline_distance is not None
                and candidate_distance is not None
                and candidate_distance < baseline_distance
            )
        )
    )
    return {
        "class_id": target.class_id,
        "ig_id": target.ig_id,
        "candidate_ig_id": target.ig_id if candidate_ig_id is None else candidate_ig_id,
        "expected_phys": expected,
        "baseline_phys": baseline_phys,
        "candidate_phys": candidate_phys,
        "satisfied": satisfied,
        "improved": improved,
        "regressed": regressed,
        "unsafe": unsafe,
    }


def _unsafe_target_result(
    baseline: AllocatorFacts,
    target: TargetAllocation,
    *,
    warning: str,
) -> dict[str, Any]:
    return {
        "class_id": target.class_id,
        "ig_id": target.ig_id,
        "candidate_ig_id": None,
        "expected_phys": target.expected_phys,
        "baseline_phys": _baseline_phys(baseline, target),
        "candidate_phys": None,
        "satisfied": False,
        "improved": False,
        "regressed": False,
        "unsafe": True,
        "warning": warning,
    }


def _candidate_status(target_results: dict[int, dict[str, Any]]) -> str:
    results = tuple(target_results.values())
    if any(result["regressed"] or result["unsafe"] for result in results):
        return "rejected"
    if results and all(result["satisfied"] for result in results):
        return "full_target_match"
    if any(result["improved"] for result in results):
        return "partial_progress"
    return "rejected"


def _guard_failure_warnings(
    validation_evidence: dict[str, object] | None,
) -> tuple[str, ...]:
    if validation_evidence is None:
        return ()

    warnings: list[str] = []
    guard_labels = {
        "checkdiff_guard": "checkdiff guard rejected candidate",
        "structural_guard": "structural guard rejected candidate",
    }
    for key, warning in guard_labels.items():
        guard = validation_evidence.get(key)
        if isinstance(guard, Mapping) and guard.get("accepted") is False:
            warnings.append(warning)
    return tuple(warnings)


def _reanchor_candidate_targets(
    baseline: AllocatorFacts,
    target_set: TargetSet,
    candidate_text: str,
    *,
    source_text: str | None,
) -> tuple[str, dict[int, TargetAllocation], dict[int, str], tuple[str, ...]]:
    if source_text is None:
        return (
            "unsafe",
            {},
            {target.ig_id: "role reanchor unavailable" for target in target_set.targets},
            ("role reanchor unavailable for candidate identity check",),
        )

    baseline_path = baseline.producer.get("path")
    if not baseline_path:
        return (
            "unsafe",
            {},
            {target.ig_id: "baseline pcdump path unavailable" for target in target_set.targets},
            ("role reanchor unavailable: baseline pcdump path unavailable",),
        )

    from .. import role_descriptor, role_reanchor  # noqa: PLC0415

    function = baseline.function.name
    baseline_text = Path(str(baseline_path)).read_text()
    baseline_compile = role_descriptor.Compile.from_text(
        baseline_text,
        function,
        source_text,
    )
    candidate_compile = role_descriptor.Compile.from_text(
        candidate_text,
        function,
        source_text,
    )

    reanchored: dict[int, TargetAllocation] = {}
    unsafe: dict[int, str] = {}
    warnings: list[str] = []
    by_class: dict[int, list[TargetAllocation]] = {}
    for target in target_set.targets:
        by_class.setdefault(target.class_id, []).append(target)

    for class_id, targets in by_class.items():
        force_phys = {target.ig_id: target.expected_phys for target in targets}
        target_spec = role_descriptor.build_target_spec(
            baseline_compile,
            force_phys,
            class_id,
            target_kind="force_proof_proxy",
            provenance={"kind": "candidate-reanchor"},
        )
        result = role_reanchor.reanchor(
            target_spec,
            candidate_compile,
            class_id=class_id,
        )
        force_phys_result = _mapping_attr(result, "force_phys")
        diagnostics = _mapping_attr(result, "diagnostics")
        matched = _mapping_attr(result, "matched")
        matched_by_original = {
            int(original_ig): int(new_ig)
            for new_ig, original_ig in matched.items()
            if new_ig in force_phys_result
        }
        for target in targets:
            new_ig = matched_by_original.get(target.ig_id)
            if new_ig is None and target.ig_id in force_phys_result:
                new_ig = target.ig_id
            if new_ig is None:
                reason = str(diagnostics.get(target.ig_id, "not reanchored"))
                warning = (
                    f"reanchor excluded protected target {target.ig_id}: {reason}"
                )
                unsafe[target.ig_id] = warning
                warnings.append(warning)
                continue
            reanchored[target.ig_id] = TargetAllocation(
                class_id=target.class_id,
                ig_id=new_ig,
                expected_phys=int(force_phys_result[new_ig]),
                source=target.source,
            )

    identity_status = "unsafe" if unsafe else "reanchored"
    return identity_status, reanchored, unsafe, tuple(warnings)


def _mapping_attr(value: object, attr: str) -> Mapping[Any, Any]:
    if isinstance(value, Mapping):
        candidate = value.get(attr, {})
    else:
        candidate = getattr(value, attr, {})
    return candidate if isinstance(candidate, Mapping) else {}


def _unsafe_comparison(
    baseline: AllocatorFacts,
    target_set: TargetSet,
    *,
    label: str,
    path: Path,
    candidate_text: str,
    identity_status: str,
    warnings: tuple[str, ...],
) -> CandidateComparison:
    target_results = {
        target.ig_id: {
            "class_id": target.class_id,
            "ig_id": target.ig_id,
            "expected_phys": target.expected_phys,
            "baseline_phys": _baseline_phys(baseline, target),
            "candidate_phys": None,
            "satisfied": False,
            "improved": False,
            "regressed": False,
            "unsafe": True,
        }
        for target in target_set.targets
    }
    return CandidateComparison(
        label=label,
        path=str(path),
        status="rejected",
        target_results=target_results,
        pressure_delta=_pressure_delta_dict(
            baseline,
            candidate_text,
            target_set,
            function=baseline.function.name,
        ),
        identity_status=identity_status,
        warnings=warnings,
    )


def _pressure_delta_dict(
    baseline: AllocatorFacts,
    candidate_text: str,
    target_set: TargetSet,
    *,
    function: str,
) -> dict[str, Any]:
    try:
        pairs = _target_pairs(target_set)
        baseline_path = baseline.producer.get("path")
        if not baseline_path:
            return {"status": "unavailable", "reason": "baseline pcdump path unavailable"}
        baseline_text = Path(str(baseline_path)).read_text()
        base_signature = pressure_signature_from_pcdump(
            baseline_text,
            function,
            pairs=pairs,
            class_id=_primary_class_id(target_set),
        )
        candidate_signature = pressure_signature_from_pcdump(
            candidate_text,
            function,
            pairs=pairs,
            class_id=_primary_class_id(target_set),
        )
        return compare_pressure_signatures(base_signature, candidate_signature).to_dict()
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "reason": str(exc)}


def _target_pairs(target_set: TargetSet) -> tuple[tuple[int, int], ...]:
    ig_ids = [target.ig_id for target in target_set.targets]
    return tuple(
        (left, right)
        for index, left in enumerate(ig_ids)
        for right in ig_ids[index + 1 :]
    )


def _target_class_ids(target_set: TargetSet) -> set[int]:
    return {target.class_id for target in target_set.targets} or {0}


def _primary_class_id(target_set: TargetSet) -> int:
    return min(_target_class_ids(target_set))


def _baseline_phys(
    baseline: AllocatorFacts,
    target: TargetAllocation,
) -> int | None:
    allocator_class = baseline.class_by_id().get(target.class_id)
    if allocator_class is None:
        return None
    node = allocator_class.node_by_ig().get(target.ig_id)
    if node is None:
        return None
    return node.assigned_phys


def _phys_distance(actual: int | None, expected: int) -> int | None:
    if actual is None:
        return None
    return abs(actual - expected)


__all__ = [
    "compare_candidate_pcdumps",
    "parse_candidate_specs",
]
