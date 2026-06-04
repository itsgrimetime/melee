"""Core harvest orchestration for taxonomy-driven harness sweeps."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.mwcc_debug.source_patch import extract_function, replace_function


SCHEMA_VERSION = 1
VALIDATED_MATCH_PERCENT = 100.0
VALIDATED_EPSILON = 1e-6

HARNESS_FRAME_TRANSFORM = "frame-transform-search"
HARNESS_COALESCE = "coalesce-search"
HARNESS_SELECT_ORDER = "select-order-search"
REGISTERED_HARNESSES = {
    HARNESS_FRAME_TRANSFORM,
    HARNESS_COALESCE,
    HARNESS_SELECT_ORDER,
}

BLOCKER_UNSUPPORTED_HARNESS = "unsupported-harness"
BLOCKER_MISSING_SOURCE_FILE = "missing-source-file"
BLOCKER_MISSING_REGISTER_TARGET = "missing-register-target"
BLOCKER_HARNESS_EXIT_NONZERO = "harness-exit-nonzero"
BLOCKER_HARNESS_INVALID_JSON = "harness-invalid-json"
BLOCKER_NO_VALIDATED_CANDIDATE = "no-validated-candidate"
BLOCKER_APPLY_TRANSFER_FAILED = "apply-transfer-failed"
BLOCKER_APPLY_VALIDATION_FAILED = "apply-validation-failed"


@dataclass
class HarvestRequest:
    function: str
    work_bucket: str
    match_percent: float
    file_path: str
    headline_tool: str
    source_file: Path | None
    primary: str = ""
    subcategory: str = ""
    source_actionability: str = ""
    frame_closability_tier: str = ""
    next_command: str = ""
    frame_next_command: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    apply: bool = False
    timeout: int = 120
    max_probes: int = 8


@dataclass
class HarnessProcessResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class HarvestResult:
    function: str
    work_bucket: str
    headline_tool: str
    status: str
    blocker: str | None
    reason: str
    command: list[str]
    candidate_path: str | None
    source_file: str | None
    final_match_percent: float | None
    applied: bool
    details: dict[str, Any] = field(default_factory=dict)
    harness: str | None = None
    primary: str = ""
    subcategory: str = ""
    source_actionability: str = ""
    frame_closability_tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HarnessRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        ...


class ValidatorRunner(Protocol):
    def __call__(
        self,
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        ...


class MatchCheckerRunner(Protocol):
    def __call__(
        self,
        function: str,
        *,
        cwd: Path,
        timeout: int,
    ) -> HarnessProcessResult:
        ...



def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_source_file(repo_root: Path, file_path: str) -> Path | None:
    """Resolve a taxonomy row source path against repo src first, then root."""
    if not file_path:
        return None
    repo_root = repo_root.resolve()
    raw_path = Path(file_path)
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        candidates = [repo_root / "src" / raw_path, repo_root / raw_path]

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_relative_to(repo_root):
            return resolved
    return None


def load_target_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("target map must be a JSON object keyed by function")
    target_map: dict[str, dict[str, Any]] = {}
    for function, facts in raw.items():
        if isinstance(facts, dict):
            target_map[str(function)] = dict(facts)
        else:
            target_map[str(function)] = {"target": facts}
    return target_map


def load_queue_rows(
    queue_path: Path,
    *,
    work_bucket: str,
    repo_root: Path,
    min_match: float = 0.0,
    limit: int | None = None,
    target_map: dict[str, dict[str, Any]] | None = None,
    apply: bool = False,
    timeout: int = 120,
    max_probes: int = 8,
) -> list[HarvestRequest]:
    rows: list[HarvestRequest] = []
    facts_by_function = target_map or {}
    with queue_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for raw in reader:
            if limit is not None and len(rows) >= limit:
                break
            match_percent = _float_or_none(raw.get("match_percent")) or 0.0
            if match_percent < min_match:
                continue
            function = (raw.get("function") or "").strip()
            if not function:
                continue
            file_path = (raw.get("file_path") or "").strip()
            rows.append(
                HarvestRequest(
                    function=function,
                    work_bucket=work_bucket,
                    match_percent=match_percent,
                    file_path=file_path,
                    headline_tool=(raw.get("headline_tool") or "").strip(),
                    source_file=resolve_source_file(repo_root, file_path),
                    primary=(raw.get("primary") or "").strip(),
                    subcategory=(raw.get("subcategory") or "").strip(),
                    source_actionability=(
                        raw.get("source_actionability") or ""
                    ).strip(),
                    frame_closability_tier=(
                        raw.get("frame_closability_tier") or ""
                    ).strip(),
                    next_command=(raw.get("next_command") or "").strip(),
                    frame_next_command=(
                        raw.get("frame_next_command") or ""
                    ).strip(),
                    facts=dict(facts_by_function.get(function, {})),
                    apply=apply,
                    timeout=timeout,
                    max_probes=max_probes,
                )
            )
    return rows


def _extract_registered_harness(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    lowered = text.strip().lower()
    if lowered in REGISTERED_HARNESSES:
        return lowered
    for harness in REGISTERED_HARNESSES:
        if harness in lowered:
            return harness
    return None


def select_harness(request: HarvestRequest) -> str | None:
    explicit_harness = request.facts.get("harness")
    if explicit_harness:
        harness = str(explicit_harness).strip().lower()
        return harness if harness in REGISTERED_HARNESSES else None

    for value in (
        request.headline_tool,
        request.source_actionability,
        request.frame_closability_tier,
        request.next_command,
        request.frame_next_command,
    ):
        harness = _extract_registered_harness(value)
        if harness is not None:
            return harness

    if request.frame_closability_tier == "current-tools-padstack":
        return HARNESS_FRAME_TRANSFORM
    return None


def extract_candidate_score(candidate: dict[str, Any]) -> float | None:
    for key in ("final_match_percent", "match_percent"):
        score = _float_or_none(candidate.get(key))
        if score is not None:
            return score
    objective = candidate.get("objective")
    if isinstance(objective, dict):
        return _float_or_none(objective.get("match_percent"))
    return None


def _is_c_source_path(value: str) -> bool:
    return Path(value).suffix == ".c"


def _candidate_source_path(candidate: dict[str, Any]) -> str | None:
    for key in (
        "source_path",
        "source_retained",
        "retained_source_path",
        "candidate_source_path",
        "generated_source_path",
        "retained_source",
    ):
        value = candidate.get(key)
        if isinstance(value, str) and value and _is_c_source_path(value):
            return value
    value = candidate.get("path")
    if isinstance(value, str) and value and _is_c_source_path(value):
        return value
    source = candidate.get("source")
    if isinstance(source, dict):
        value = source.get("path")
        if isinstance(value, str) and value and _is_c_source_path(value):
            return value
    return None


def _iter_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "variants",
        "ranked_variants",
        "candidates",
        "ranked_candidates",
        "results",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        return [candidate]
    if (
        _candidate_source_path(payload) is not None
        and extract_candidate_score(payload) is not None
    ):
        return [payload]
    return []


def best_validated_candidate(payload: Any) -> dict[str, Any] | None:
    for candidate in _iter_candidates(payload):
        if candidate.get("status") != "ok":
            continue
        if _candidate_source_path(candidate) is None:
            continue
        score = extract_candidate_score(candidate)
        if score is None:
            continue
        if abs(score - VALIDATED_MATCH_PERCENT) <= VALIDATED_EPSILON:
            return candidate
    return None


def _default_runner(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [sys.executable, "-m", "src.cli", *args]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout + 30,
    )
    return HarnessProcessResult(
        command=list(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_validator(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [sys.executable, "tools/checkdiff.py", function, "--compact"]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return HarnessProcessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _default_match_checker(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return HarnessProcessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _frame_transform_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_FRAME_TRANSFORM,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _coalesce_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        HARNESS_COALESCE,
        "-f",
        request.function,
        "--target",
        str(request.facts["target"]),
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _select_order_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        HARNESS_SELECT_ORDER,
        "-f",
        request.function,
        "--target",
        str(request.facts["target"]),
        "--class",
        str(request.facts.get("class_id", 0)),
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _base_result(
    request: HarvestRequest,
    *,
    harness: str | None,
    status: str,
    blocker: str | None,
    reason: str,
    command: list[str] | None = None,
    candidate_path: str | None = None,
    final_match_percent: float | None = None,
    applied: bool = False,
    details: dict[str, Any] | None = None,
) -> HarvestResult:
    return HarvestResult(
        function=request.function,
        work_bucket=request.work_bucket,
        headline_tool=request.headline_tool,
        status=status,
        blocker=blocker,
        reason=reason,
        command=command or [],
        candidate_path=candidate_path,
        source_file=str(request.source_file) if request.source_file else None,
        final_match_percent=final_match_percent,
        applied=applied,
        details=details or {},
        harness=harness,
        primary=request.primary,
        subcategory=request.subcategory,
        source_actionability=request.source_actionability,
        frame_closability_tier=request.frame_closability_tier,
    )


def _short_output(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _match_checker_indicates_match(process: HarnessProcessResult) -> bool:
    if process.returncode != 0:
        return False
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and "match" in payload:
        return payload.get("match") is True
    return True


def _already_matched_result(
    request: HarvestRequest,
    *,
    repo_root: Path,
    harness: str | None,
    match_checker: MatchCheckerRunner,
) -> HarvestResult | None:
    try:
        process = match_checker(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
    except Exception:
        return None
    if not _match_checker_indicates_match(process):
        return None
    return _base_result(
        request,
        harness=harness,
        status="already-matched",
        blocker=None,
        reason="function already matches; stale queue row skipped",
        command=process.command,
        details={
            "stdout": _short_output(process.stdout),
            "stderr": _short_output(process.stderr),
        },
    )


def _matched_functions_in_source_file(
    repo_root: Path,
    source_file: Path,
    *,
    exclude: str,
) -> list[str]:
    report_path = repo_root / "build" / "GALE01" / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    source_resolved = source_file.resolve()
    matched: list[str] = []
    for unit in report.get("units") or []:
        if not isinstance(unit, dict):
            continue
        metadata = unit.get("metadata") or {}
        unit_source = metadata.get("source_path") or unit.get("name")
        if not isinstance(unit_source, str) or not unit_source:
            continue
        unit_source_path = Path(unit_source)
        if not unit_source_path.is_absolute():
            unit_source_path = repo_root / unit_source_path
        try:
            if unit_source_path.resolve() != source_resolved:
                continue
        except OSError:
            continue
        for function in unit.get("functions") or []:
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or name == exclude:
                continue
            score = _float_or_none(function.get("fuzzy_match_percent"))
            if score is not None and score >= VALIDATED_MATCH_PERCENT:
                matched.append(name)
    return matched


def _candidate_path_for_apply(candidate_path: str, repo_root: Path) -> Path:
    path = Path(candidate_path)
    if path.is_absolute():
        return path
    for base in (repo_root, repo_root / "tools" / "melee-agent"):
        candidate = base / path
        if candidate.exists():
            return candidate
    return repo_root / path


def _atomic_write_text(path: Path, text: str) -> None:
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(text)
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def _apply_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate_path: str,
    validator: ValidatorRunner,
    harness: str,
    command: list[str],
    final_match_percent: float,
) -> HarvestResult:
    if request.source_file is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    candidate_file = _candidate_path_for_apply(candidate_path, repo_root)
    try:
        candidate_text = candidate_file.read_text(encoding="utf-8")
        target_text = request.source_file.read_text(encoding="utf-8")
    except OSError as exc:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate or target source could not be read",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    candidate_function = extract_function(candidate_text, request.function)
    if candidate_function is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate source did not contain the requested function",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    patched = replace_function(target_text, request.function, candidate_function)
    if patched is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="target source did not contain the requested function",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    try:
        _atomic_write_text(request.source_file, patched)
        validation = validator(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
    except BaseException as exc:
        try:
            _atomic_write_text(request.source_file, target_text)
        except Exception as rollback_exc:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "error": str(exc),
                    "rollback_error": str(rollback_exc),
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply validation failed to run",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    if validation.returncode != 0:
        try:
            _atomic_write_text(request.source_file, target_text)
        except Exception as rollback_exc:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "validator_command": validation.command,
                    "validator_stdout": _short_output(validation.stdout),
                    "validator_stderr": _short_output(validation.stderr),
                    "rollback_error": str(rollback_exc),
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply validation failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "validator_command": validation.command,
                "validator_stdout": _short_output(validation.stdout),
                "validator_stderr": _short_output(validation.stderr),
            },
        )

    for matched_function in _matched_functions_in_source_file(
        repo_root,
        request.source_file,
        exclude=request.function,
    ):
        try:
            regression = validator(
                matched_function,
                cwd=repo_root,
                timeout=request.timeout,
            )
        except BaseException as exc:
            try:
                _atomic_write_text(request.source_file, target_text)
            except Exception as rollback_exc:
                return _base_result(
                    request,
                    harness=harness,
                    status="blocked",
                    blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                    reason="post-apply regression guard failed and rollback failed",
                    command=command,
                    candidate_path=candidate_path,
                    final_match_percent=final_match_percent,
                    details={
                        "regression_function": matched_function,
                        "error": str(exc),
                        "rollback_error": str(rollback_exc),
                    },
                )
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply regression guard failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "regression_function": matched_function,
                    "error": str(exc),
                },
            )
        if regression.returncode == 0:
            continue
        try:
            _atomic_write_text(request.source_file, target_text)
        except Exception as rollback_exc:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply regression guard failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "regression_function": matched_function,
                    "validator_command": regression.command,
                    "validator_stdout": _short_output(regression.stdout),
                    "validator_stderr": _short_output(regression.stderr),
                    "rollback_error": str(rollback_exc),
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="post-apply regression guard failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "regression_function": matched_function,
                "validator_command": regression.command,
                "validator_stdout": _short_output(regression.stdout),
                "validator_stderr": _short_output(regression.stderr),
            },
        )

    return _base_result(
        request,
        harness=harness,
        status="applied",
        blocker=None,
        reason="validated candidate applied",
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
        applied=True,
        details={"validator_command": validation.command},
    )


def _adapter_command(request: HarvestRequest, harness: str) -> list[str]:
    if harness == HARNESS_FRAME_TRANSFORM:
        return _frame_transform_command(request)
    if harness == HARNESS_COALESCE:
        return _coalesce_command(request)
    if harness == HARNESS_SELECT_ORDER:
        return _select_order_command(request)
    raise ValueError(f"unsupported harness: {harness}")


def run_harvest_request(
    request: HarvestRequest,
    *,
    repo_root: Path,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> HarvestResult:
    harness = select_harness(request)
    if request.apply:
        already_matched = _already_matched_result(
            request,
            repo_root=repo_root,
            harness=harness,
            match_checker=match_checker,
        )
        if already_matched is not None:
            return already_matched

    if harness is None:
        return _base_result(
            request,
            harness=None,
            status="unsupported",
            blocker=BLOCKER_UNSUPPORTED_HARNESS,
            reason="no registered harness matched the row",
        )

    if request.source_file is None:
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
        )

    if harness in {HARNESS_COALESCE, HARNESS_SELECT_ORDER} and not request.facts.get(
        "target"
    ):
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_REGISTER_TARGET,
            reason="register harness requires facts.target",
        )

    command = _adapter_command(request, harness)
    try:
        process = runner(
            command,
            cwd=repo_root / "tools" / "melee-agent",
            timeout=request.timeout,
        )
    except Exception as exc:
        return _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess failed to run",
            command=command,
            details={"error": str(exc)},
        )

    if process.returncode != 0:
        return _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess exited nonzero",
            command=command,
            details={
                "returncode": process.returncode,
                "stdout": _short_output(process.stdout),
                "stderr": _short_output(process.stderr),
            },
        )

    try:
        harness_json = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_INVALID_JSON,
            reason="harness did not emit valid JSON",
            command=command,
            details={"error": str(exc), "stdout": _short_output(process.stdout)},
        )

    candidate = best_validated_candidate(harness_json)
    if candidate is None:
        return _base_result(
            request,
            harness=harness,
            status="no_match",
            blocker=BLOCKER_NO_VALIDATED_CANDIDATE,
            reason="no validated 100% candidate was found",
            command=command,
            details={"candidate_count": len(_iter_candidates(harness_json))},
        )

    final_match_percent = extract_candidate_score(candidate)
    candidate_path = _candidate_source_path(candidate)
    assert final_match_percent is not None
    assert candidate_path is not None
    if not request.apply:
        return _base_result(
            request,
            harness=harness,
            status="validated",
            blocker=None,
            reason="validated candidate found",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

    return _apply_candidate(
        request,
        repo_root=repo_root,
        candidate_path=candidate_path,
        validator=validator,
        harness=harness,
        command=command,
        final_match_percent=final_match_percent,
    )


def summarize_ledger(results: list[HarvestResult | dict[str, Any]]) -> dict[str, Any]:
    normalized = [
        result.to_dict() if isinstance(result, HarvestResult) else result
        for result in results
    ]
    by_status: Counter[str] = Counter()
    by_harness: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()
    by_blocker: Counter[str] = Counter()

    for result in normalized:
        by_status[str(result.get("status") or "unknown")] += 1
        by_harness[str(result.get("harness") or "unsupported")] += 1
        tier = (
            result.get("frame_closability_tier")
            or result.get("source_actionability")
            or "unclassified"
        )
        by_tier[str(tier)] += 1
        blocker = result.get("blocker")
        if blocker:
            by_blocker[str(blocker)] += 1

    return {
        "total_rows": len(normalized),
        "processed": len(normalized),
        "by_status": dict(by_status),
        "by_harness": dict(by_harness),
        "by_tier": dict(by_tier),
        "by_blocker": dict(by_blocker),
    }


def _build_ledger(
    *,
    work_bucket: str,
    started_at: str,
    finished_at: str,
    apply: bool,
    min_match: float,
    limit: int | None,
    taxonomy_queue: Path,
    target_map_path: Path | None,
    results: list[HarvestResult | dict[str, Any]],
) -> dict[str, Any]:
    result_dicts = [
        result.to_dict() if isinstance(result, HarvestResult) else result
        for result in results
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "work_bucket": work_bucket,
        "started_at": started_at,
        "finished_at": finished_at,
        "apply": apply,
        "min_match": min_match,
        "limit": limit,
        "taxonomy_queue": str(taxonomy_queue),
        "target_map": str(target_map_path) if target_map_path else None,
        "summary": summarize_ledger(result_dicts),
        "results": result_dicts,
    }


def write_ledger(
    path: Path,
    *,
    work_bucket: str,
    started_at: str,
    finished_at: str,
    apply: bool,
    min_match: float,
    limit: int | None,
    taxonomy_queue: Path,
    target_map_path: Path | None,
    results: list[HarvestResult | dict[str, Any]],
) -> dict[str, Any]:
    ledger = _build_ledger(
        work_bucket=work_bucket,
        started_at=started_at,
        finished_at=finished_at,
        apply=apply,
        min_match=min_match,
        limit=limit,
        taxonomy_queue=taxonomy_queue,
        target_map_path=target_map_path,
        results=results,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ledger


def run_harvest(
    work_bucket: str,
    *,
    repo_root: Path,
    queue_path: Path | None = None,
    taxonomy_dir: Path | None = None,
    min_match: float = 0.0,
    limit: int | None = None,
    target_map: dict[str, dict[str, Any]] | None = None,
    target_map_path: Path | None = None,
    ledger_path: Path | None = None,
    apply: bool = False,
    timeout: int = 120,
    max_probes: int = 8,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> dict[str, Any]:
    started_at = _utc_now()
    if queue_path is None:
        queue_root = (
            taxonomy_dir
            if taxonomy_dir is not None
            else repo_root / "build" / "function-taxonomy" / "queues"
        )
        queue_path = queue_root / f"{work_bucket}.tsv"

    if target_map is None:
        target_map = load_target_map(target_map_path)

    requests = load_queue_rows(
        queue_path,
        work_bucket=work_bucket,
        repo_root=repo_root,
        min_match=min_match,
        limit=limit,
        target_map=target_map,
        apply=apply,
        timeout=timeout,
        max_probes=max_probes,
    )
    results = [
        run_harvest_request(
            request,
            repo_root=repo_root,
            runner=runner,
            validator=validator,
            match_checker=match_checker,
        )
        for request in requests
    ]
    finished_at = _utc_now()
    if ledger_path is not None:
        return write_ledger(
            ledger_path,
            work_bucket=work_bucket,
            started_at=started_at,
            finished_at=finished_at,
            apply=apply,
            min_match=min_match,
            limit=limit,
            taxonomy_queue=queue_path,
            target_map_path=target_map_path,
            results=results,
        )
    return _build_ledger(
        work_bucket=work_bucket,
        started_at=started_at,
        finished_at=finished_at,
        apply=apply,
        min_match=min_match,
        limit=limit,
        taxonomy_queue=queue_path,
        target_map_path=target_map_path,
        results=results,
    )
