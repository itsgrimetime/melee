from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .analyzer import analyze_lifetime_pressure
from .candidates import compare_candidate_pcdumps, parse_candidate_specs
from .facts import facts_from_backend_trace, facts_from_pcdump
from .hypotheses import attach_hypotheses
from .models import CandidateSpec, LifetimePressureReport, TargetSet, ValidationCommand
from .targets import parse_force_phys_spec, parse_target_file
from .validation import (
    build_remote_validation_plan,
    materialize_force_phys_target_spec,
    run_bounded_validation,
    run_quick_validation,
)

_VALIDATE_MODES = {"none", "remote", "quick", "bounded"}


def build_lifetime_pressure_report(
    *,
    function: str,
    pcdump_text: str | None,
    pcdump_path: Path | None,
    source_text: str | None,
    source_path: Path | None,
    force_phys: str | None,
    target_path: Path | None,
    candidates: list[str],
    backend_trace_path: Path | None,
    class_id: int,
    allow_stale_pcdump: bool,
    validate_mode: str,
    timeout: int,
    max_candidates: int,
) -> LifetimePressureReport:
    if validate_mode not in _VALIDATE_MODES:
        raise ValueError(f"unknown validation mode {validate_mode!r}")

    target_set = _load_target_set(
        target_path=target_path,
        force_phys=force_phys,
        class_id=class_id,
    )
    effective_source_text = _effective_source_text(source_text, source_path)
    facts = (
        facts_from_backend_trace(backend_trace_path, function=function)
        if backend_trace_path is not None
        else facts_from_pcdump(
            _effective_pcdump_text(pcdump_text, pcdump_path),
            function,
            pcdump_path=pcdump_path,
            source_text=effective_source_text,
            source_path=source_path,
        )
    )

    report = analyze_lifetime_pressure(
        facts,
        target_set,
        allow_stale_pcdump=allow_stale_pcdump,
    )
    if target_set is not None and target_set.targets:
        report = attach_hypotheses(
            report,
            pcdump_path=pcdump_path,
            source_path=source_path,
            allow_stale_pcdump=allow_stale_pcdump,
        )

    candidate_specs = parse_candidate_specs(candidates, validate_mode=validate_mode)
    report = _attach_candidate_comparisons(
        report,
        facts=facts,
        target_set=target_set,
        candidate_specs=candidate_specs,
        source_text=effective_source_text,
    )
    report = _attach_validation(
        report,
        function=function,
        force_phys=force_phys,
        target_path=target_path,
        target_set=target_set,
        pcdump_path=pcdump_path,
        source_path=source_path,
        candidate_specs=candidate_specs,
        class_id=class_id,
        validate_mode=validate_mode,
        timeout=timeout,
        max_candidates=max_candidates,
    )
    return report


def _effective_pcdump_text(pcdump_text: str | None, pcdump_path: Path | None) -> str:
    if pcdump_text is not None:
        return pcdump_text
    if pcdump_path is not None and pcdump_path.exists():
        return pcdump_path.read_text()
    raise ValueError("pcdump_text is required unless backend_trace_path is provided")


def _effective_source_text(
    source_text: str | None,
    source_path: Path | None,
) -> str | None:
    if source_text is not None:
        return source_text
    if source_path is not None and source_path.exists():
        return source_path.read_text()
    return None


def _load_target_set(
    *,
    target_path: Path | None,
    force_phys: str | None,
    class_id: int,
) -> TargetSet | None:
    if target_path is not None:
        return parse_target_file(target_path)
    if force_phys is not None:
        return parse_force_phys_spec(force_phys, default_class_id=class_id)
    return None


def _attach_candidate_comparisons(
    report: LifetimePressureReport,
    *,
    facts,
    target_set: TargetSet | None,
    candidate_specs: tuple[CandidateSpec, ...],
    source_text: str | None,
) -> LifetimePressureReport:
    pcdump_candidates = [
        (candidate.label, Path(candidate.path))
        for candidate in candidate_specs
        if candidate.kind == "pcdump"
    ]
    if not pcdump_candidates:
        return report
    if target_set is None:
        return replace(
            report,
            warnings=(
                *report.warnings,
                "pcdump candidate comparisons require an explicit target",
            ),
        )

    comparisons = compare_candidate_pcdumps(
        facts,
        target_set,
        candidates=pcdump_candidates,
        source_text=source_text,
    )
    return replace(
        report,
        candidate_comparisons=(*report.candidate_comparisons, *comparisons),
    )


def _attach_validation(
    report: LifetimePressureReport,
    *,
    function: str,
    force_phys: str | None,
    target_path: Path | None,
    target_set: TargetSet | None,
    pcdump_path: Path | None,
    source_path: Path | None,
    candidate_specs: tuple[CandidateSpec, ...],
    class_id: int,
    validate_mode: str,
    timeout: int,
    max_candidates: int,
) -> LifetimePressureReport:
    source_candidates = _source_candidate_paths(candidate_specs)
    if validate_mode == "remote":
        return _attach_remote_validation_plan(
            report,
            function=function,
            force_phys=force_phys,
            target_path=target_path,
            target_set=target_set,
            pcdump_path=pcdump_path,
            source_path=source_path,
            source_candidates=source_candidates,
            timeout=timeout,
        )
    if validate_mode == "quick":
        return _attach_quick_validation(
            report,
            function=function,
            force_phys=force_phys,
            target_path=target_path,
            pcdump_path=pcdump_path,
            source_candidates=source_candidates,
            class_id=class_id,
            timeout=timeout,
        )
    if validate_mode == "bounded":
        return _attach_bounded_validation(
            report,
            function=function,
            force_phys=force_phys,
            target_path=target_path,
            pcdump_path=pcdump_path,
            source_path=source_path,
            source_candidates=source_candidates,
            class_id=class_id,
            timeout=timeout,
            max_candidates=max_candidates,
        )
    return report


def _source_candidate_paths(candidate_specs: tuple[CandidateSpec, ...]) -> list[Path]:
    return [
        Path(candidate.path)
        for candidate in candidate_specs
        if candidate.kind in {"source", "source-dry-run"}
    ]


def _attach_remote_validation_plan(
    report: LifetimePressureReport,
    *,
    function: str,
    force_phys: str | None,
    target_path: Path | None,
    target_set: TargetSet | None,
    pcdump_path: Path | None,
    source_path: Path | None,
    source_candidates: list[Path],
    timeout: int,
) -> LifetimePressureReport:
    effective_force_phys = force_phys or _force_phys_from_target_set(target_set)
    if effective_force_phys is None:
        return replace(
            report,
            warnings=(*report.warnings, "remote validation requires targets"),
        )

    commands = build_remote_validation_plan(
        function=function,
        force_phys=effective_force_phys,
        timeout=timeout,
        campaign_dir=_campaign_dir(
            target_path=target_path,
            pcdump_path=pcdump_path,
            source_path=source_path,
        ),
        source_candidates=source_candidates,
        target_file=target_path,
    )
    return replace(
        report,
        validation_commands=_dedupe_validation_commands(
            (*report.validation_commands, *commands)
        ),
    )


def _attach_quick_validation(
    report: LifetimePressureReport,
    *,
    function: str,
    force_phys: str | None,
    target_path: Path | None,
    pcdump_path: Path | None,
    source_candidates: list[Path],
    class_id: int,
    timeout: int,
) -> LifetimePressureReport:
    if not source_candidates:
        return report

    quick_target_path = target_path
    if quick_target_path is None and force_phys is not None and pcdump_path is not None:
        quick_target_path = materialize_force_phys_target_spec(
            function=function,
            class_id=class_id,
            force_phys=force_phys,
            baseline_dump=pcdump_path,
            output_dir=pcdump_path.parent,
        )
    if quick_target_path is None:
        return replace(
            report,
            warnings=(
                *report.warnings,
                "quick validation requires a target file or force-phys pcdump",
            ),
        )

    results = run_quick_validation(
        function=function,
        target_file=quick_target_path,
        source_candidates=source_candidates,
        timeout=timeout,
    )
    return _append_output(report, "quick_validation", results)


def _attach_bounded_validation(
    report: LifetimePressureReport,
    *,
    function: str,
    force_phys: str | None,
    target_path: Path | None,
    pcdump_path: Path | None,
    source_path: Path | None,
    source_candidates: list[Path],
    class_id: int,
    timeout: int,
    max_candidates: int,
) -> LifetimePressureReport:
    if source_candidates:
        bounded_source_target_path = target_path
        if (
            bounded_source_target_path is None
            and force_phys is not None
            and pcdump_path is not None
        ):
            bounded_source_target_path = materialize_force_phys_target_spec(
                function=function,
                class_id=class_id,
                force_phys=force_phys,
                baseline_dump=pcdump_path,
                output_dir=pcdump_path.parent,
            )
        if bounded_source_target_path is None:
            report = replace(
                report,
                warnings=(
                    *report.warnings,
                    "bounded source validation requires a target file or force-phys pcdump",
                ),
            )
        else:
            source_results = run_quick_validation(
                function=function,
                target_file=bounded_source_target_path,
                source_candidates=source_candidates,
                timeout=timeout,
            )
            report = _append_output(
                report,
                "bounded_source_validation",
                source_results,
            )

    if force_phys is None or pcdump_path is None or source_path is None:
        return replace(
            report,
            warnings=(
                *report.warnings,
                "bounded validation requires force_phys, pcdump_path, and source_path",
            ),
        )

    results = run_bounded_validation(
        function=function,
        force_phys=force_phys,
        pcdump_path=pcdump_path,
        source_path=source_path,
        timeout=timeout,
        max_candidates=max_candidates,
        direct_blockers=_direct_blockers(report),
    )
    return _append_output(report, "bounded_validation", results)


def _direct_blockers(report: LifetimePressureReport) -> list[tuple[int, int, int]]:
    blockers: list[tuple[int, int, int]] = []
    for target in report.targets:
        if not target.blockers:
            continue
        primary = target.blockers[0]
        if primary.ig_id is not None:
            blockers.append((target.class_id, target.ig_id, primary.ig_id))
    return blockers


def _force_phys_from_target_set(target_set: TargetSet | None) -> str | None:
    if target_set is None or not target_set.targets:
        return None
    entries: list[str] = []
    for target in target_set.targets:
        if target.class_id == 0:
            entries.append(f"{target.ig_id}:{target.expected_phys}")
        else:
            entries.append(f"{target.class_id}:{target.ig_id}:{target.expected_phys}")
    return ",".join(entries)


def _campaign_dir(
    *,
    target_path: Path | None,
    pcdump_path: Path | None,
    source_path: Path | None,
) -> Path:
    for path in (target_path, pcdump_path, source_path):
        if path is not None:
            return path.parent
    return Path.cwd()


def _append_output(
    report: LifetimePressureReport,
    key: str,
    value: object,
) -> LifetimePressureReport:
    outputs = dict(report.outputs)
    outputs[key] = value
    return replace(report, outputs=outputs)


def _dedupe_validation_commands(
    commands: tuple[ValidationCommand, ...],
) -> tuple[ValidationCommand, ...]:
    deduped: dict[tuple[str, str], ValidationCommand] = {}
    for command in commands:
        deduped.setdefault((command.id, command.command), command)
    return tuple(deduped.values())


__all__ = ["build_lifetime_pressure_report"]
