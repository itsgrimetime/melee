"""Real build-tree scorer for retained structure-search variants."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.search.adapters import _acquire_repo_build_lock
from src.search.structure import StructureScoreResult, StructureVariant
from src.mwcc_debug.diff_capture import _run_with_process_group_timeout


@dataclass(frozen=True)
class StructureScoreContext:
    melee_root: Path
    function: str
    unit: str
    source_path: Path
    build_obj_path: Path
    report_path: Path


def resolve_structure_score_context(
    melee_root: Path,
    function: str,
    source_path: Path,
) -> StructureScoreContext:
    melee_root = Path(melee_root).resolve()
    source_path = Path(source_path).resolve()
    report_path = melee_root / "build" / "GALE01" / "report.json"
    report = _read_json_file(report_path)

    for unit in report.get("units", []) or []:
        if not isinstance(unit, dict):
            continue
        functions = unit.get("functions") or []
        if not any(
            isinstance(row, dict) and row.get("name") == function
            for row in functions
        ):
            continue
        unit_name = _normalize_report_unit_name(unit.get("name"))
        if not unit_name:
            raise ValueError(f"report.json unit for {function} has no name")
        resolved_source = _source_path_for_unit(melee_root, unit, unit_name)
        if resolved_source.resolve() != source_path:
            raise ValueError(
                f"source mismatch for {function}: report.json resolves "
                f"{resolved_source}, got {source_path}"
            )
        return StructureScoreContext(
            melee_root=melee_root,
            function=function,
            unit=unit_name,
            source_path=resolved_source,
            build_obj_path=melee_root / "build" / "GALE01" / "src" / f"{unit_name}.o",
            report_path=report_path,
        )

    raise ValueError(f"function not found in build/GALE01/report.json: {function}")


def score_structure_variants(
    *,
    melee_root: Path,
    function: str,
    source_path: Path,
    variants: list[StructureVariant],
    timeout: float,
) -> list[StructureScoreResult]:
    context = resolve_structure_score_context(melee_root, function, source_path)
    scoreable = [variant for variant in variants if variant.source_retained]
    if not scoreable:
        return []

    with _acquire_repo_build_lock(context.melee_root, label="structure scoring"):
        original_source = context.source_path.read_bytes()
        original_obj = (
            context.build_obj_path.read_bytes()
            if context.build_obj_path.exists()
            else None
        )
        original_report = (
            context.report_path.read_bytes()
            if context.report_path.exists()
            else None
        )
        history_path = _checkdiff_history_path(context)
        history_dir_existed = history_path.parent.exists()
        original_history = (
            history_path.read_bytes()
            if history_path.exists()
            else None
        )
        try:
            context.source_path.write_bytes(original_source)
            baseline_status, baseline_reason = _build_unit(context, timeout)
            if baseline_status != "ok":
                return [
                    StructureScoreResult(
                        label=variant.label,
                        baseline_percent=None,
                        candidate_percent=None,
                        compile_status=baseline_status,
                        unscored_reason=f"baseline compile failed: {baseline_reason}",
                    )
                    for variant in scoreable
                ]
            try:
                baseline_percent = _refresh_report_percent(context, timeout)
            except RuntimeError as exc:
                return [
                    StructureScoreResult(
                        label=variant.label,
                        baseline_percent=None,
                        candidate_percent=None,
                        compile_status="report-failed",
                        unscored_reason=f"baseline report failed: {exc}",
                    )
                    for variant in scoreable
                ]
            baseline_structural: dict[str, Any] = {}
            baseline_checkdiff_reason: str | None = None
            try:
                baseline_structural = _run_checkdiff(context, timeout)
            except RuntimeError as exc:
                baseline_checkdiff_reason = str(exc)

            results: list[StructureScoreResult] = []
            for variant in scoreable:
                results.append(
                    _score_one_variant(
                        context,
                        variant,
                        baseline_percent=baseline_percent,
                        baseline_structural=baseline_structural,
                        baseline_checkdiff_reason=baseline_checkdiff_reason,
                        timeout=timeout,
                    )
                )
            return results
        finally:
            context.source_path.write_bytes(original_source)
            _restore_optional_file(context.build_obj_path, original_obj)
            _restore_optional_file(context.report_path, original_report)
            _restore_checkdiff_history(
                history_path,
                original_history,
                history_dir_existed=history_dir_existed,
            )


def _score_one_variant(
    context: StructureScoreContext,
    variant: StructureVariant,
    *,
    baseline_percent: float | None,
    baseline_structural: dict[str, Any],
    baseline_checkdiff_reason: str | None,
    timeout: float,
) -> StructureScoreResult:
    assert variant.source_retained is not None
    candidate_path = Path(variant.source_retained).expanduser()
    try:
        candidate_source = candidate_path.read_bytes()
    except OSError as exc:
        return StructureScoreResult(
            label=variant.label,
            baseline_percent=baseline_percent,
            candidate_percent=None,
            compile_status="source-unavailable",
            unscored_reason=f"candidate source unavailable: {exc}",
        )

    context.source_path.write_bytes(candidate_source)
    compile_status, compile_reason = _build_unit(context, timeout)
    if compile_status != "ok":
        return StructureScoreResult(
            label=variant.label,
            baseline_percent=baseline_percent,
            candidate_percent=None,
            compile_status=compile_status,
            unscored_reason=f"candidate compile failed: {compile_reason}",
        )

    try:
        candidate_percent = _refresh_report_percent(context, timeout)
    except RuntimeError as exc:
        return StructureScoreResult(
            label=variant.label,
            baseline_percent=baseline_percent,
            candidate_percent=None,
            compile_status="report-failed",
            unscored_reason=f"candidate report failed: {exc}",
        )

    try:
        candidate_structural = _run_checkdiff(context, timeout)
    except RuntimeError as exc:
        return StructureScoreResult(
            label=variant.label,
            baseline_percent=baseline_percent,
            candidate_percent=candidate_percent,
            compile_status="ok",
            checkdiff_status="failed",
            unscored_reason=f"candidate checkdiff failed: {exc}",
        )

    if baseline_checkdiff_reason is not None:
        return StructureScoreResult(
            label=variant.label,
            baseline_percent=baseline_percent,
            candidate_percent=candidate_percent,
            compile_status="ok",
            checkdiff_status="failed",
            unscored_reason=f"baseline checkdiff failed: {baseline_checkdiff_reason}",
            structural=candidate_structural,
        )

    return StructureScoreResult(
        label=variant.label,
        baseline_percent=baseline_percent,
        candidate_percent=candidate_percent,
        compile_status="ok",
        checkdiff_status="ok",
        structural=_structural_with_deltas(baseline_structural, candidate_structural),
    )


def _build_unit(
    context: StructureScoreContext,
    timeout: float,
) -> tuple[str, str]:
    obj_rel = f"build/GALE01/src/{context.unit}.o"
    try:
        proc = _run_child(
            ["ninja", obj_rel],
            cwd=context.melee_root,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "failed", f"ninja {obj_rel} timed out after {timeout}s"
    if proc.returncode == 0:
        return "ok", ""
    return "failed", _process_detail(proc)


def _refresh_report_percent(
    context: StructureScoreContext,
    timeout: float,
) -> float | None:
    objdiff_bin = context.melee_root / "build" / "tools" / "objdiff-cli"
    if objdiff_bin.exists():
        cmd = [
            str(objdiff_bin),
            "report",
            "generate",
            "-o",
            str(context.report_path),
            "-f",
            "json",
        ]
    else:
        cmd = ["ninja", "build/GALE01/report.json"]
    try:
        proc = _run_child(
            cmd,
            cwd=context.melee_root,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{' '.join(str(part) for part in cmd)} timed out after {timeout}s"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(_process_detail(proc))
    percent = _read_report_percent(context.report_path, context.function)
    if percent is None:
        raise RuntimeError(
            f"report.json did not contain match percent for {context.function}"
        )
    return percent


def _run_checkdiff(
    context: StructureScoreContext,
    timeout: float,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["CHECKDIFF_NO_LOCK"] = "1"
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    try:
        proc = _run_child(
            [
                "python",
                "tools/checkdiff.py",
                context.function,
                "--format",
                "json",
                "--no-build",
            ],
            cwd=context.melee_root,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"tools/checkdiff.py {context.function} timed out after {timeout}s"
        ) from exc
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        raise RuntimeError(_process_detail(proc))
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"checkdiff emitted non-json: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("checkdiff JSON root was not an object")
    return _extract_structural_metrics(payload)


def _extract_structural_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("structural")
    if not isinstance(source, dict):
        source = payload
    metrics: dict[str, Any] = {}
    for key in ("opcode_similarity", "line_delta", "hunk_count"):
        if key in source:
            metrics[key] = source[key]
    return metrics


def _structural_with_deltas(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    structural = dict(candidate)
    if "opcode_similarity" in candidate:
        try:
            structural["opcode_shape_preserved"] = (
                float(candidate["opcode_similarity"]) >= 1.0
            )
        except (TypeError, ValueError):
            pass
    for key in ("opcode_similarity", "line_delta", "hunk_count"):
        if key not in candidate or key not in baseline:
            continue
        delta_key = f"{key}_delta"
        structural[delta_key] = _numeric_delta(candidate[key], baseline[key])
    return structural


def _numeric_delta(value: Any, baseline: Any) -> float | int:
    delta = float(value) - float(baseline)
    if isinstance(value, int) and isinstance(baseline, int):
        return int(delta)
    return round(delta, 6)


def _read_report_percent(report_path: Path, function: str) -> float | None:
    report = _read_json_file(report_path)
    for unit in report.get("units", []) or []:
        if not isinstance(unit, dict):
            continue
        for row in unit.get("functions") or []:
            if not isinstance(row, dict) or row.get("name") != function:
                continue
            for key in ("fuzzy_match_percent", "match_percent", "percent"):
                if row.get(key) is not None:
                    return float(row[key])
    return None


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} JSON root was not an object")
    return payload


def _normalize_report_unit_name(value: Any) -> str:
    unit = str(value or "").removeprefix("main/").removesuffix(".c")
    return unit.removeprefix("src/")


def _source_path_for_unit(
    melee_root: Path,
    unit: dict[str, Any],
    unit_name: str,
) -> Path:
    for key in ("source_path", "source", "path"):
        raw = unit.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = melee_root / path
        if path.suffix == ".c":
            return path.resolve()
    return (melee_root / "src" / f"{unit_name}.c").resolve()


def _restore_optional_file(path: Path, original: bytes | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)


def _checkdiff_history_path(context: StructureScoreContext) -> Path:
    return (
        context.melee_root
        / "build"
        / ".checkdiff-history"
        / f"{context.function}.json"
    )


def _restore_checkdiff_history(
    path: Path,
    original: bytes | None,
    *,
    history_dir_existed: bool,
) -> None:
    _restore_optional_file(path, original)
    if history_dir_existed:
        return
    try:
        path.parent.rmdir()
    except OSError:
        pass


def _run_child(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run_with_process_group_timeout(
        [str(part) for part in cmd],
        cwd=cwd,
        timeout=timeout,
        env=env,
    )


def _process_detail(proc: subprocess.CompletedProcess) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    return detail or f"exit {proc.returncode}"
