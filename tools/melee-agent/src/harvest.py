"""Core harvest orchestration for taxonomy-driven harness sweeps."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.mwcc_debug.source_patch import extract_function, replace_function


SCHEMA_VERSION = 1
VALIDATED_MATCH_PERCENT = 100.0
VALIDATED_EPSILON = 1e-6

HARNESS_FRAME_TRANSFORM = "frame-transform-search"
HARNESS_COALESCE = "coalesce-search"
HARNESS_SELECT_ORDER = "select-order-search"
HARNESS_INDEXED_STRUCT = "indexed-struct-search"
HARNESS_NAME_MAGIC_SOURCE = "name-magic-source-declarations"
REGISTERED_HARNESSES = {
    HARNESS_FRAME_TRANSFORM,
    HARNESS_COALESCE,
    HARNESS_SELECT_ORDER,
    HARNESS_INDEXED_STRUCT,
    HARNESS_NAME_MAGIC_SOURCE,
}

BLOCKER_UNSUPPORTED_HARNESS = "unsupported-harness"
BLOCKER_MISSING_SOURCE_FILE = "missing-source-file"
BLOCKER_MISSING_REGISTER_TARGET = "missing-register-target"
BLOCKER_HARNESS_EXIT_NONZERO = "harness-exit-nonzero"
BLOCKER_HARNESS_INVALID_JSON = "harness-invalid-json"
BLOCKER_NO_VALIDATED_CANDIDATE = "no-validated-candidate"
BLOCKER_APPLY_TRANSFER_FAILED = "apply-transfer-failed"
BLOCKER_APPLY_VALIDATION_FAILED = "apply-validation-failed"
BLOCKER_DECLARATION_APPLY_UNSUPPORTED = "declaration-apply-unsupported"


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

    if request.primary == "data-symbol-relocation":
        return HARNESS_NAME_MAGIC_SOURCE
    if request.work_bucket == "data-symbol-relocation" and (
        request.primary == "data-symbol-or-relocation"
        or request.subcategory == "persistent-data-symbol-or-relocation"
        or request.source_actionability == "current-tools-data-symbol"
        or request.headline_tool == "checkdiff-name-magic"
    ):
        return HARNESS_NAME_MAGIC_SOURCE

    if request.primary == "indexed-struct-pointer-materialization":
        return HARNESS_INDEXED_STRUCT
    if request.source_actionability == "current-tools-indexed-pointer":
        return HARNESS_INDEXED_STRUCT

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


def _candidate_source_path_any(candidate: dict[str, Any]) -> str | None:
    for key in (
        "source_path",
        "source_retained",
        "retained_source_path",
        "candidate_source_path",
        "generated_source_path",
        "retained_source",
    ):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value
    value = candidate.get("path")
    if isinstance(value, str) and value:
        return value
    source = candidate.get("source")
    if isinstance(source, dict):
        value = source.get("path")
        if isinstance(value, str) and value:
            return value
    return None


def _candidate_source_path(candidate: dict[str, Any]) -> str | None:
    value = _candidate_source_path_any(candidate)
    if value is not None and _is_c_source_path(value):
        return value
    return None


def _candidate_header_path(candidate: Mapping[str, Any] | None) -> str | None:
    if candidate is None:
        return None
    for key in (
        "header_path",
        "header_retained",
        "retained_header_path",
        "candidate_header_path",
        "generated_header_path",
        "retained_header",
    ):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value
    header = candidate.get("header")
    if isinstance(header, Mapping):
        value = header.get("path")
        if isinstance(value, str) and value:
            return value
    return None


def _candidate_header_target(
    candidate: Mapping[str, Any] | None,
    request: HarvestRequest,
    repo_root: Path,
) -> Path | None:
    if candidate is not None:
        value = candidate.get("header_target")
        if isinstance(value, str) and value:
            return _candidate_path_for_apply(value, repo_root)
    if request.source_file is None:
        return None
    return request.source_file.with_suffix(".h")


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


def _name_magic_source_stop_kind(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    stop = payload.get("stop_condition")
    if not isinstance(stop, dict):
        return None
    kind = stop.get("kind")
    return kind if isinstance(kind, str) else None


def _name_magic_candidate_score(candidate: dict[str, Any]) -> float | None:
    for key in ("final_match_percent", "match_percent"):
        score = _float_or_none(candidate.get(key))
        if score is not None:
            return score
    return None


def _is_valid_name_magic_candidate(candidate: dict[str, Any]) -> bool:
    if candidate.get("status") != "ok":
        return False
    if candidate.get("no_name_magic_match") is not True:
        return False
    score = _name_magic_candidate_score(candidate)
    if score is None:
        return False
    return abs(score - VALIDATED_MATCH_PERCENT) <= VALIDATED_EPSILON


def best_validated_name_magic_candidate(
    payload: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    if _name_magic_source_stop_kind(payload) != "validated":
        return None, None
    for candidate in _iter_candidates(payload):
        if not _is_valid_name_magic_candidate(candidate):
            continue
        candidate_path = _candidate_source_path(candidate)
        if candidate_path is not None:
            return candidate, None
        raw_path = _candidate_source_path_any(candidate)
        if raw_path is not None and not _is_c_source_path(raw_path):
            return None, raw_path
    return None, None


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


def _default_no_name_magic_validator(
    function: str,
    *,
    cwd: Path,
    timeout: int,
) -> HarnessProcessResult:
    command = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--compact",
        "--no-name-magic",
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


def _default_no_name_magic_match_checker(
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
        "--no-name-magic",
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


def _indexed_struct_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_INDEXED_STRUCT,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--score-match-percent",
        "--json",
        "--max-probes",
        str(request.max_probes),
        "--timeout",
        str(request.timeout),
    ]


def _name_magic_source_command(request: HarvestRequest) -> list[str]:
    assert request.source_file is not None
    return [
        "debug",
        "mutate",
        HARNESS_NAME_MAGIC_SOURCE,
        "-f",
        request.function,
        "--source-file",
        str(request.source_file),
        "--compile-probes",
        "--score-match-percent",
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


def _strict_match_payload(process: HarnessProcessResult) -> dict[str, Any] | None:
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _strict_payload_indicates_match(payload: Mapping[str, Any] | None) -> bool:
    return payload is not None and payload.get("match") is True


def _payload_match_percent(payload: Mapping[str, Any] | None) -> float | None:
    if payload is None:
        return None
    for key in ("fuzzy_match_percent", "match_percent", "final_match_percent"):
        score = _float_or_none(payload.get(key))
        if score is not None:
            return score
    objective = payload.get("objective")
    if isinstance(objective, Mapping):
        return _float_or_none(objective.get("match_percent"))
    return None


def _payload_classification(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if payload is None:
        return {}
    classification = payload.get("classification")
    return classification if isinstance(classification, Mapping) else {}


def _payload_classification_primary(payload: Mapping[str, Any] | None) -> str:
    primary = _payload_classification(payload).get("primary")
    return str(primary) if isinstance(primary, str) else ""


def _classification_has_layer_signal(
    payload: Mapping[str, Any] | None,
    harness: str,
) -> bool:
    classification = _payload_classification(payload)
    primary = _payload_classification_primary(payload)
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        return (
            primary in {"data-symbol-or-relocation", "data-symbol-relocation"}
            or "data-symbol" in primary
        )
    if harness == HARNESS_INDEXED_STRUCT:
        return (
            primary == "indexed-struct-pointer-materialization"
            or "indexed_struct_pointer_materialization" in classification
            or "indexed-struct" in primary
        )
    if harness == HARNESS_FRAME_TRANSFORM:
        return (
            "stack" in primary
            or "frame" in primary
            or "stack_frame_delta" in classification
            or "stack_slot_layout_cause" in classification
            or "stack_slot_localizer" in classification
        )
    if harness in {HARNESS_COALESCE, HARNESS_SELECT_ORDER}:
        return "register" in primary
    return False


def _payload_verifies_layer_improvement(
    before_payload: Mapping[str, Any] | None,
    after_payload: Mapping[str, Any] | None,
    *,
    harness: str,
) -> bool:
    if _strict_payload_indicates_match(after_payload):
        return True
    if after_payload is None:
        return False
    before_score = _payload_match_percent(before_payload)
    after_score = _payload_match_percent(after_payload)
    if (
        before_score is not None
        and after_score is not None
        and after_score > before_score + VALIDATED_EPSILON
    ):
        return True
    return _classification_has_layer_signal(
        before_payload,
        harness,
    ) and not _classification_has_layer_signal(after_payload, harness)


def _harness_blocker_result(payload: Any) -> tuple[str, str, str] | None:
    if not isinstance(payload, dict):
        return None
    blocker = payload.get("blocker")
    stop = payload.get("stop_condition")
    reason = None
    kind = "no_match"
    if isinstance(stop, dict):
        blocker = blocker or stop.get("blocker")
        reason = stop.get("reason")
        stop_kind = stop.get("kind")
        if stop_kind == "blocked":
            kind = "blocked"
        elif stop_kind == "unvalidated":
            kind = "no_match"
    if isinstance(blocker, str) and blocker:
        return kind, blocker, str(reason or blocker)
    return None


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


def _same_file_regression_error(
    request: HarvestRequest,
    *,
    repo_root: Path,
    validator: ValidatorRunner,
) -> dict[str, Any] | None:
    if request.source_file is None:
        return None
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
            return {
                "regression_function": matched_function,
                "error": str(exc),
            }
        if regression.returncode == 0:
            continue
        return {
            "regression_function": matched_function,
            "validator_command": regression.command,
            "validator_stdout": _short_output(regression.stdout),
            "validator_stderr": _short_output(regression.stderr),
        }
    return None


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


@dataclass(frozen=True)
class _HeaderApplyCandidate:
    candidate_path: str
    target_path: Path
    candidate_text: str
    target_text: str


def _read_optional_header_apply_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate: Mapping[str, Any] | None,
    harness: str,
    command: list[str],
    candidate_path: str,
    final_match_percent: float,
) -> tuple[_HeaderApplyCandidate | None, HarvestResult | None]:
    header_candidate_path = _candidate_header_path(candidate)
    if header_candidate_path is None:
        return None, None

    candidate_file = _candidate_path_for_apply(header_candidate_path, repo_root)
    if candidate_file.suffix != ".h":
        return None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
            reason="retained header candidate is not a .h file",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"header_candidate_path": header_candidate_path},
        )

    target_header = _candidate_header_target(candidate, request, repo_root)
    if target_header is None or not target_header.exists():
        return None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
            reason="target header for retained source candidate was not found",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"header_candidate_path": str(candidate_file)},
        )

    try:
        candidate_text = candidate_file.read_text(encoding="utf-8")
        target_text = target_header.read_text(encoding="utf-8")
    except OSError as exc:
        return None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_TRANSFER_FAILED,
            reason="candidate or target header could not be read",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={
                "header_candidate_path": str(candidate_file),
                "header_target": str(target_header),
                "error": str(exc),
            },
        )

    return (
        _HeaderApplyCandidate(
            candidate_path=str(candidate_file),
            target_path=target_header,
            candidate_text=candidate_text,
            target_text=target_text,
        ),
        None,
    )


def _restore_apply_targets(
    source_file: Path,
    source_text: str,
    header_candidate: _HeaderApplyCandidate | None = None,
) -> str | None:
    errors: list[str] = []
    try:
        _atomic_write_text(source_file, source_text)
    except Exception as exc:
        errors.append(str(exc))
    if header_candidate is not None:
        try:
            _atomic_write_text(
                header_candidate.target_path,
                header_candidate.target_text,
            )
        except Exception as exc:
            errors.append(str(exc))
    return "; ".join(errors) if errors else None


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


def _apply_whole_file_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate_path: str,
    candidate: Mapping[str, Any] | None = None,
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
    if not _is_c_source_path(str(candidate_file)):
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
            reason="retained source candidate is not a .c file",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
        )

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

    header_candidate, header_error = _read_optional_header_apply_candidate(
        request,
        repo_root=repo_root,
        candidate=candidate,
        harness=harness,
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
    )
    if header_error is not None:
        return header_error

    try:
        if header_candidate is not None:
            _atomic_write_text(
                header_candidate.target_path,
                header_candidate.candidate_text,
            )
        _atomic_write_text(request.source_file, candidate_text)
        validation = validator(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
    except BaseException as exc:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
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
                    "rollback_error": rollback_error,
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
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
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
                    "rollback_error": rollback_error,
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

    regression_error = _same_file_regression_error(
        request,
        repo_root=repo_root,
        validator=validator,
    )
    if regression_error is not None:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="post-apply regression guard failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={**regression_error, "rollback_error": rollback_error},
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
            details=regression_error,
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
        details={
            "validator_command": validation.command,
            **(
                {
                    "header_candidate_path": header_candidate.candidate_path,
                    "header_target": str(header_candidate.target_path),
                }
                if header_candidate is not None
                else {}
            ),
        },
    )


def _adapter_command(request: HarvestRequest, harness: str) -> list[str]:
    if harness == HARNESS_FRAME_TRANSFORM:
        return _frame_transform_command(request)
    if harness == HARNESS_COALESCE:
        return _coalesce_command(request)
    if harness == HARNESS_SELECT_ORDER:
        return _select_order_command(request)
    if harness == HARNESS_INDEXED_STRUCT:
        return _indexed_struct_command(request)
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        return _name_magic_source_command(request)
    raise ValueError(f"unsupported harness: {harness}")


def _normalize_layer_sequence(request: HarvestRequest) -> list[dict[str, Any]]:
    explicit = request.facts.get("harnesses")
    if isinstance(explicit, list):
        layers: list[dict[str, Any]] = []
        for item in explicit:
            if isinstance(item, str):
                harness = item.strip().lower()
                if harness:
                    layers.append({"harness": harness})
            elif isinstance(item, Mapping):
                layer = dict(item)
                harness = layer.get("harness")
                if harness:
                    layer["harness"] = str(harness).strip().lower()
                    layers.append(layer)
        return layers

    selected: list[str] = []
    if (
        request.work_bucket == "data-symbol-relocation"
        or request.primary in {"data-symbol-or-relocation", "data-symbol-relocation"}
        or request.source_actionability == "current-tools-data-symbol"
        or request.headline_tool == "checkdiff-name-magic"
    ):
        selected.append(HARNESS_NAME_MAGIC_SOURCE)
    if (
        request.primary == "indexed-struct-pointer-materialization"
        or request.source_actionability == "current-tools-indexed-pointer"
    ):
        selected.append(HARNESS_INDEXED_STRUCT)
    row_harness = select_harness(request)
    if row_harness is not None:
        selected.append(row_harness)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for harness in selected:
        if harness in seen:
            continue
        seen.add(harness)
        deduped.append({"harness": harness})
    return deduped


def _layer_request(request: HarvestRequest, layer_facts: Mapping[str, Any]) -> HarvestRequest:
    facts = dict(request.facts)
    facts.pop("harnesses", None)
    facts.update(dict(layer_facts))
    return replace(request, facts=facts)


def _execute_harness_payload(
    request: HarvestRequest,
    *,
    harness: str,
    repo_root: Path,
    runner: HarnessRunner,
) -> tuple[list[str], Any | None, HarvestResult | None]:
    if harness not in REGISTERED_HARNESSES:
        return [], None, _base_result(
            request,
            harness=harness,
            status="unsupported",
            blocker=BLOCKER_UNSUPPORTED_HARNESS,
            reason="no registered harness matched the layer",
        )
    if request.source_file is None:
        return [], None, _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_MISSING_SOURCE_FILE,
            reason="source file could not be resolved",
        )
    if harness in {HARNESS_COALESCE, HARNESS_SELECT_ORDER} and not request.facts.get(
        "target"
    ):
        return [], None, _base_result(
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
        return command, None, _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_EXIT_NONZERO,
            reason="harness subprocess failed to run",
            command=command,
            details={"error": str(exc)},
        )
    if process.returncode != 0:
        return command, None, _base_result(
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
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        return command, None, _base_result(
            request,
            harness=harness,
            status="error",
            blocker=BLOCKER_HARNESS_INVALID_JSON,
            reason="harness did not emit valid JSON",
            command=command,
            details={"error": str(exc), "stdout": _short_output(process.stdout)},
        )
    return command, payload, None


def _rank_sub100_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates = []
    for candidate in _iter_candidates(payload):
        if candidate.get("status") != "ok":
            continue
        if _candidate_source_path(candidate) is None:
            continue
        score = extract_candidate_score(candidate)
        if score is None:
            continue
        if abs(score - VALIDATED_MATCH_PERCENT) <= VALIDATED_EPSILON:
            continue
        candidates.append(candidate)
    candidates.sort(
        key=lambda candidate: (
            extract_candidate_score(candidate)
            if extract_candidate_score(candidate) is not None
            else -1.0
        ),
        reverse=True,
    )
    return candidates


def _apply_partial_layer_candidate(
    request: HarvestRequest,
    *,
    repo_root: Path,
    candidate_path: str,
    candidate: Mapping[str, Any] | None = None,
    match_checker: MatchCheckerRunner,
    validator: ValidatorRunner,
    harness: str,
    command: list[str],
    final_match_percent: float,
    before_payload: Mapping[str, Any] | None,
    preserve: bool,
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

    header_candidate, header_error = _read_optional_header_apply_candidate(
        request,
        repo_root=repo_root,
        candidate=candidate,
        harness=harness,
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
    )
    if header_error is not None:
        return header_error

    if harness == HARNESS_NAME_MAGIC_SOURCE:
        patched = candidate_text
    else:
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
        if header_candidate is not None:
            _atomic_write_text(
                header_candidate.target_path,
                header_candidate.candidate_text,
            )
        _atomic_write_text(request.source_file, patched)
        after_process = match_checker(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
        after_payload = _strict_match_payload(after_process)
        verified = _payload_verifies_layer_improvement(
            before_payload,
            after_payload,
            harness=harness,
        )
        regression_error = (
            _same_file_regression_error(
                request,
                repo_root=repo_root,
                validator=validator,
            )
            if verified
            else None
        )
    except BaseException as exc:
        rollback_error = _restore_apply_targets(
            request.source_file,
            target_text,
            header_candidate,
        )
        if rollback_error is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_APPLY_VALIDATION_FAILED,
                reason="partial layer validation failed and rollback failed",
                command=command,
                candidate_path=candidate_path,
                final_match_percent=final_match_percent,
                details={
                    "error": str(exc),
                    "rollback_error": rollback_error,
                },
            )
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="partial layer validation failed to run",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details={"error": str(exc)},
        )

    details = {
        "layer_outcome": "verified-improvement" if verified else "not-improved",
        "before_match_percent": _payload_match_percent(before_payload),
        "after_match_percent": _payload_match_percent(after_payload),
        "before_classification": _payload_classification_primary(before_payload),
        "after_classification": _payload_classification_primary(after_payload),
        "after_match_checker_command": after_process.command,
        "after_match_checker_stdout": _short_output(after_process.stdout),
        "after_match_checker_stderr": _short_output(after_process.stderr),
    }
    if header_candidate is not None:
        details["header_candidate_path"] = header_candidate.candidate_path
        details["header_target"] = str(header_candidate.target_path)
    if regression_error is not None:
        details.update(regression_error)

    if verified and regression_error is None and preserve:
        return _base_result(
            request,
            harness=harness,
            status="applied",
            blocker=None,
            reason="verified layer improvement applied",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            applied=True,
            details=details,
        )

    rollback_error = _restore_apply_targets(
        request.source_file,
        target_text,
        header_candidate,
    )
    if rollback_error is not None:
        details["rollback_error"] = rollback_error
        return _base_result(
            request,
            harness=harness,
            status="blocked",
            blocker=BLOCKER_APPLY_VALIDATION_FAILED,
            reason="partial layer validation failed and rollback failed",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            details=details,
        )

    if verified and regression_error is None:
        return _base_result(
            request,
            harness=harness,
            status="improved",
            blocker=None,
            reason="verified layer improvement found",
            command=command,
            candidate_path=candidate_path,
            final_match_percent=final_match_percent,
            applied=False,
            details=details,
        )

    return _base_result(
        request,
        harness=harness,
        status="blocked",
        blocker=BLOCKER_APPLY_VALIDATION_FAILED,
        reason=(
            "post-apply regression guard failed"
            if regression_error is not None
            else "candidate did not verify a strict post-apply improvement"
        ),
        command=command,
        candidate_path=candidate_path,
        final_match_percent=final_match_percent,
        details=details,
    )


def _compose_result(
    request: HarvestRequest,
    *,
    status: str,
    blocker: str | None,
    reason: str,
    layers: list[HarvestResult],
    harness_sequence: list[str],
    stop_reason: str,
    not_observed_layers: list[str] | None = None,
    final_layer: HarvestResult | None = None,
    applied: bool | None = None,
) -> HarvestResult:
    final_layer = final_layer or (layers[-1] if layers else None)
    details = {
        "layers": [layer.to_dict() for layer in layers],
        "stop_reason": stop_reason,
        "harness_sequence": harness_sequence,
        "not_observed_layers": not_observed_layers or [],
    }
    return _base_result(
        request,
        harness="composed",
        status=status,
        blocker=blocker,
        reason=reason,
        command=final_layer.command if final_layer is not None else [],
        candidate_path=final_layer.candidate_path if final_layer is not None else None,
        final_match_percent=(
            final_layer.final_match_percent if final_layer is not None else None
        ),
        applied=(
            any(layer.applied for layer in layers)
            if applied is None
            else applied
        ),
        details=details,
    )


def run_composed_harvest_request(
    request: HarvestRequest,
    *,
    repo_root: Path,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> HarvestResult:
    layer_facts = _normalize_layer_sequence(request)
    harness_sequence = [str(layer.get("harness") or "") for layer in layer_facts]
    if not layer_facts:
        return _compose_result(
            request,
            status="unsupported",
            blocker=BLOCKER_UNSUPPORTED_HARNESS,
            reason="no harness sequence was available for composition",
            layers=[],
            harness_sequence=[],
            stop_reason="empty-harness-sequence",
        )

    layers: list[HarvestResult] = []
    for index, facts in enumerate(layer_facts):
        harness = str(facts.get("harness") or "").strip().lower()
        layer_request = _layer_request(request, facts)
        layer_validator = validator
        layer_match_checker = match_checker
        if harness == HARNESS_NAME_MAGIC_SOURCE:
            if validator is _default_validator:
                layer_validator = _default_no_name_magic_validator
            if match_checker is _default_match_checker:
                layer_match_checker = _default_no_name_magic_match_checker

        before_payload: dict[str, Any] | None = None
        try:
            before_process = layer_match_checker(
                request.function,
                cwd=repo_root,
                timeout=request.timeout,
            )
            before_payload = _strict_match_payload(before_process)
        except Exception:
            before_process = None
        if _strict_payload_indicates_match(before_payload):
            if layers:
                return _compose_result(
                    request,
                    status="already-matched",
                    blocker=None,
                    reason="function reached match=true after composed layers",
                    layers=layers,
                    harness_sequence=harness_sequence,
                    stop_reason="matched-after-layers",
                    final_layer=layers[-1],
                )
            return _compose_result(
                request,
                status="already-matched",
                blocker=None,
                reason="function already matches; stale queue row skipped",
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason="already-matched-before-layer",
                final_layer=layers[-1] if layers else None,
            )

        command, payload, error_result = _execute_harness_payload(
            layer_request,
            harness=harness,
            repo_root=repo_root,
            runner=runner,
        )
        if error_result is not None:
            layers.append(error_result)
            return _compose_result(
                request,
                status=error_result.status,
                blocker=error_result.blocker,
                reason=error_result.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason=f"layer-{error_result.status}",
                final_layer=error_result,
            )

        assert payload is not None
        if harness == HARNESS_NAME_MAGIC_SOURCE:
            candidate, unsupported_candidate_path = best_validated_name_magic_candidate(
                payload
            )
        else:
            candidate = best_validated_candidate(payload)
            unsupported_candidate_path = None

        if candidate is not None:
            final_match_percent = extract_candidate_score(candidate)
            candidate_path = _candidate_source_path(candidate)
            assert final_match_percent is not None
            assert candidate_path is not None
            if not request.apply:
                layer = _base_result(
                    layer_request,
                    harness=harness,
                    status="validated",
                    blocker=None,
                    reason="validated candidate found",
                    command=command,
                    candidate_path=candidate_path,
                    final_match_percent=final_match_percent,
                )
                layers.append(layer)
                return _compose_result(
                    request,
                    status="validated",
                    blocker=None,
                    reason="validated candidate found",
                    layers=layers,
                    harness_sequence=harness_sequence,
                    stop_reason="dry-run-first-candidate-layer",
                    not_observed_layers=harness_sequence[index + 1 :],
                    final_layer=layer,
                    applied=False,
                )
            if harness == HARNESS_NAME_MAGIC_SOURCE:
                layer = _apply_whole_file_candidate(
                    layer_request,
                    repo_root=repo_root,
                    candidate_path=candidate_path,
                    candidate=candidate,
                    validator=layer_validator,
                    harness=harness,
                    command=command,
                    final_match_percent=final_match_percent,
                )
            else:
                layer = _apply_candidate(
                    layer_request,
                    repo_root=repo_root,
                    candidate_path=candidate_path,
                    validator=layer_validator,
                    harness=harness,
                    command=command,
                    final_match_percent=final_match_percent,
                )
            layers.append(layer)
            if layer.status not in {"applied", "validated"}:
                return _compose_result(
                    request,
                    status=layer.status,
                    blocker=layer.blocker,
                    reason=layer.reason,
                    layers=layers,
                    harness_sequence=harness_sequence,
                    stop_reason=f"layer-{layer.status}",
                    final_layer=layer,
                )
            continue

        if unsupported_candidate_path is not None:
            layer = _base_result(
                layer_request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
                reason="retained source candidate is not a .c file",
                command=command,
                candidate_path=unsupported_candidate_path,
                details={"candidate_count": len(_iter_candidates(payload))},
            )
            layers.append(layer)
            return _compose_result(
                request,
                status=layer.status,
                blocker=layer.blocker,
                reason=layer.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason="layer-blocked",
                final_layer=layer,
            )

        sub100_candidates = _rank_sub100_candidates(payload)
        last_failed_layer: HarvestResult | None = None
        for sub_candidate in sub100_candidates:
            final_match_percent = extract_candidate_score(sub_candidate)
            candidate_path = _candidate_source_path(sub_candidate)
            assert final_match_percent is not None
            assert candidate_path is not None
            layer = _apply_partial_layer_candidate(
                layer_request,
                repo_root=repo_root,
                candidate_path=candidate_path,
                candidate=sub_candidate,
                match_checker=layer_match_checker,
                validator=layer_validator,
                harness=harness,
                command=command,
                final_match_percent=final_match_percent,
                before_payload=before_payload,
                preserve=request.apply,
            )
            if layer.status in {"applied", "improved"}:
                layers.append(layer)
                if not request.apply:
                    return _compose_result(
                        request,
                        status="improved",
                        blocker=None,
                        reason="verified layer improvement found",
                        layers=layers,
                        harness_sequence=harness_sequence,
                        stop_reason="dry-run-first-candidate-layer",
                        not_observed_layers=harness_sequence[index + 1 :],
                        final_layer=layer,
                        applied=False,
                    )
                break
            last_failed_layer = layer
        else:
            harness_blocker = _harness_blocker_result(payload)
            if harness_blocker is not None:
                status, blocker, reason = harness_blocker
                layer = _base_result(
                    layer_request,
                    harness=harness,
                    status=status,
                    blocker=blocker,
                    reason=reason,
                    command=command,
                    details={"candidate_count": len(_iter_candidates(payload))},
                )
            elif last_failed_layer is not None:
                layer = last_failed_layer
            else:
                layer = _base_result(
                    layer_request,
                    harness=harness,
                    status="no_match",
                    blocker=BLOCKER_NO_VALIDATED_CANDIDATE,
                    reason="no validated 100% candidate was found",
                    command=command,
                    details={"candidate_count": len(_iter_candidates(payload))},
                )
            layers.append(layer)
            return _compose_result(
                request,
                status=layer.status,
                blocker=layer.blocker,
                reason=layer.reason,
                layers=layers,
                harness_sequence=harness_sequence,
                stop_reason=f"layer-{layer.status}",
                final_layer=layer,
            )

    try:
        final_process = match_checker(
            request.function,
            cwd=repo_root,
            timeout=request.timeout,
        )
        final_payload = _strict_match_payload(final_process)
    except Exception:
        final_payload = None
    if _strict_payload_indicates_match(final_payload):
        return _compose_result(
            request,
            status="already-matched",
            blocker=None,
            reason="function reached match=true after composed layers",
            layers=layers,
            harness_sequence=harness_sequence,
            stop_reason="matched-after-layers",
            final_layer=layers[-1] if layers else None,
        )

    final_layer = layers[-1]
    return _compose_result(
        request,
        status=final_layer.status,
        blocker=final_layer.blocker,
        reason=final_layer.reason,
        layers=layers,
        harness_sequence=harness_sequence,
        stop_reason="layer-sequence-exhausted",
        final_layer=final_layer,
    )


def run_harvest_request(
    request: HarvestRequest,
    *,
    repo_root: Path,
    runner: HarnessRunner = _default_runner,
    validator: ValidatorRunner = _default_validator,
    match_checker: MatchCheckerRunner = _default_match_checker,
) -> HarvestResult:
    harness = select_harness(request)
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        if validator is _default_validator:
            validator = _default_no_name_magic_validator
        if match_checker is _default_match_checker:
            match_checker = _default_no_name_magic_match_checker

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

    unsupported_candidate_path = None
    if harness == HARNESS_NAME_MAGIC_SOURCE:
        candidate, unsupported_candidate_path = best_validated_name_magic_candidate(
            harness_json
        )
    else:
        candidate = best_validated_candidate(harness_json)
    if candidate is None:
        if unsupported_candidate_path is not None:
            return _base_result(
                request,
                harness=harness,
                status="blocked",
                blocker=BLOCKER_DECLARATION_APPLY_UNSUPPORTED,
                reason="retained source candidate is not a .c file",
                command=command,
                candidate_path=unsupported_candidate_path,
                details={"candidate_count": len(_iter_candidates(harness_json))},
            )
        harness_blocker = _harness_blocker_result(harness_json)
        if harness_blocker is not None:
            status, blocker, reason = harness_blocker
            return _base_result(
                request,
                harness=harness,
                status=status,
                blocker=blocker,
                reason=reason,
                command=command,
                details={"candidate_count": len(_iter_candidates(harness_json))},
            )
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

    if harness == HARNESS_NAME_MAGIC_SOURCE:
        return _apply_whole_file_candidate(
            request,
            repo_root=repo_root,
            candidate_path=candidate_path,
            candidate=candidate,
            validator=validator,
            harness=harness,
            command=command,
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
    compose: bool = False,
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
    request_runner = run_composed_harvest_request if compose else run_harvest_request
    results = [
        request_runner(
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
