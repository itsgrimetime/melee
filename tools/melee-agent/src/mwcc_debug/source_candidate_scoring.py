"""Shared score-source handoff helpers for retained C candidates."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ScoreSourceConfig:
    repo_root: Path
    function: str
    target: Path | None
    cflags_from: Path | str
    expression_source: Path | str | None
    expression_baseline: Path | None
    expression_reg_class: str
    output_dir: Path
    timeout: float
    checkdiff_guard: bool = True
    full_unit_source: bool = True
    remote: bool = False
    remote_fallback: bool = False


@dataclass(frozen=True)
class SourceCandidate:
    candidate_id: str
    source_text: str
    summary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_hunks: Sequence[Mapping[str, Any]] = ()


ScoreSourceRunner = Callable[..., subprocess.CompletedProcess[str]]


def write_retained_source_candidates(
    candidates: Sequence[SourceCandidate | Mapping[str, Any]],
    config: ScoreSourceConfig,
) -> list[dict[str, Any]]:
    """Write full-unit source candidates and return score-source input rows."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, candidate in enumerate(candidates, start=1):
        candidate_id = _candidate_id(candidate, fallback=f"candidate-{index:04d}")
        safe_name = _unique_safe_name(candidate_id, used_names)
        source_path = config.output_dir / f"{safe_name}.c"
        source_path.write_text(_candidate_source_text(candidate), encoding="utf-8")
        metadata = _candidate_metadata(candidate)
        row: dict[str, Any] = {
            "candidate_id": candidate_id,
            "source_file": str(source_path),
            "source_retained": str(source_path),
            "full_unit_source": config.full_unit_source,
            "source_hunks": _candidate_source_hunks(candidate),
        }
        summary = _candidate_summary(candidate)
        if summary:
            row["summary"] = summary
        row.update(metadata)
        rows.append(row)
    return rows


def score_source_candidates(
    candidates: Sequence[SourceCandidate | Mapping[str, Any]],
    config: ScoreSourceConfig,
    *,
    runner: ScoreSourceRunner | None = None,
) -> list[dict[str, Any]]:
    rows = write_retained_source_candidates(candidates, config)
    return score_retained_source_rows(rows, config, runner=runner)


def score_retained_source_rows(
    rows: Sequence[Mapping[str, Any]],
    config: ScoreSourceConfig,
    *,
    runner: ScoreSourceRunner | None = None,
) -> list[dict[str, Any]]:
    """Score already-retained source rows via ``debug target score-source``."""

    score_runner = runner or subprocess.run
    out: list[dict[str, Any]] = []
    env = _score_source_env(config.repo_root)
    for row in rows:
        candidate_id = row.get("candidate_id")
        candidate_path = _row_candidate_path(row)
        row_full_unit = bool(row.get("full_unit_source", config.full_unit_source))
        row_score_function = str(row.get("score_function") or config.function)
        if candidate_path is None:
            out.append(_finalize_score_row(
                _with_score_source_scope_defaults(
                    {
                        **dict(row),
                        "candidate_id": candidate_id,
                        "error": "candidate-path-missing",
                        "score_error_kind": "infrastructure",
                        "full_unit_source": row_full_unit,
                        "blockers": [
                            {
                                "reason": "score-source-error:candidate-path-missing",
                                "candidate_id": candidate_id,
                            }
                        ],
                    },
                    input_row=row,
                    config=config,
                    candidate_path=None,
                    score_function=row_score_function,
                )
            ))
            continue

        cmd = build_score_source_command(
            candidate_path,
            config,
            function=row_score_function,
            full_unit_source=row_full_unit,
        )
        score_command = " ".join(shlex.quote(part) for part in cmd)
        try:
            proc = score_runner(
                cmd,
                cwd=config.repo_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=(
                    config.timeout + 10
                    if config.timeout and config.timeout > 0
                    else None
                ),
                check=False,
            )
        except KeyboardInterrupt:
            out.append(_finalize_score_row(
                _with_score_source_scope_defaults(
                    {
                        **dict(row),
                        "candidate_id": candidate_id,
                        "source_file": str(candidate_path),
                        "source_retained": str(candidate_path),
                        "error": "score-source-interrupted",
                        "score_error_kind": "infrastructure",
                        "score_returncode": 130,
                        "score_command": score_command,
                        "full_unit_source": row_full_unit,
                        "score_stderr": (
                            "Interrupted while scoring source candidate "
                            f"{candidate_id}"
                        ),
                        "blockers": [
                            {
                                "reason": "live-score-interrupted",
                                "candidate_id": candidate_id,
                            }
                        ],
                    },
                    input_row=row,
                    config=config,
                    candidate_path=candidate_path,
                    score_function=row_score_function,
                )
            ))
            break
        except subprocess.TimeoutExpired as exc:
            out.append(_finalize_score_row(
                _with_score_source_scope_defaults(
                    {
                        **dict(row),
                        "candidate_id": candidate_id,
                        "source_file": str(candidate_path),
                        "source_retained": str(candidate_path),
                        "error": "score-source-timeout",
                        "score_error_kind": "infrastructure",
                        "score_returncode": 124,
                        "score_command": score_command,
                        "full_unit_source": row_full_unit,
                        "score_stderr": _timeout_stream_text(exc.stderr)
                        or f"Timed out while scoring source candidate {candidate_id}",
                        "raw_stdout": _timeout_stream_text(exc.stdout) or "",
                        "timeout_seconds": exc.timeout,
                        "blockers": [
                            {
                                "reason": "live-score-timeout",
                                "candidate_id": candidate_id,
                                "timeout_seconds": exc.timeout,
                            }
                        ],
                    },
                    input_row=row,
                    config=config,
                    candidate_path=candidate_path,
                    score_function=row_score_function,
                )
            ))
            break

        payload = _parse_score_source_stdout(proc.stdout)
        merged = dict(row)
        merged.update(payload)
        if candidate_id is not None:
            # The CLI derives an ID from the retained filename.  The caller's
            # manifest ID is authoritative for cache keys and mask identity.
            merged["candidate_id"] = candidate_id
        else:
            merged.setdefault("candidate_id", candidate_id)
        merged.setdefault("source_file", str(candidate_path))
        merged.setdefault("source_retained", str(candidate_path))
        merged["full_unit_source"] = row_full_unit
        merged["score_command"] = score_command
        merged["score_returncode"] = proc.returncode
        merged = _with_score_source_scope_defaults(
            merged,
            input_row=row,
            config=config,
            candidate_path=candidate_path,
            score_function=row_score_function,
        )
        if proc.returncode != 0 and merged.get("error") is None:
            merged["error"] = f"score-source exited {proc.returncode}"
        if proc.stderr:
            merged["score_stderr"] = proc.stderr
        out.append(_finalize_score_row(merged))
    return out


def _with_score_source_scope_defaults(
    row: Mapping[str, Any],
    *,
    input_row: Mapping[str, Any],
    config: ScoreSourceConfig,
    candidate_path: Path | None,
    score_function: str,
) -> dict[str, Any]:
    out = dict(row)
    candidate_id = input_row.get("candidate_id")
    if candidate_id is not None:
        out.setdefault("candidate_id", candidate_id)
    dimension_id = input_row.get("dimension_id")
    if dimension_id is not None:
        out.setdefault("dimension_id", dimension_id)
    source_model_layer_dimension_id = input_row.get("source_model_layer_dimension_id")
    if source_model_layer_dimension_id is not None:
        out.setdefault("source_model_layer_dimension_id", source_model_layer_dimension_id)
    out.setdefault("function", input_row.get("function") or config.function)
    out.setdefault("score_function", score_function)
    source_path = candidate_path or _row_candidate_path(input_row)
    if source_path is not None:
        source_text = str(source_path)
        out.setdefault("source_file", source_text)
        out.setdefault("source_retained", source_text)
        out.setdefault("c_file", source_text)
    out.setdefault("cflags_from", str(config.cflags_from))
    return out


def build_score_source_command(
    candidate_path: Path,
    config: ScoreSourceConfig,
    *,
    function: str,
    full_unit_source: bool,
) -> list[str]:
    expression_source = (
        config.expression_source
        if config.expression_source is not None
        else config.cflags_from
    )
    cmd = [
        sys.executable,
        "-m",
        "src.cli",
        "debug",
        "target",
        "score-source",
        str(candidate_path),
        "--function",
        function,
        "--cflags-from",
        str(config.cflags_from),
        "--expression-source",
        str(expression_source),
        "--expression-reg-class",
        config.expression_reg_class,
        "--retain-pcdump",
        "--json",
    ]
    if config.target is not None:
        cmd.extend(["--target", str(config.target)])
    if config.expression_baseline is not None:
        cmd.extend(["--expression-baseline", str(config.expression_baseline)])
    if full_unit_source:
        cmd.append("--full-unit-source")
    if config.checkdiff_guard:
        cmd.append("--checkdiff-guard")
    else:
        cmd.append("--no-checkdiff-guard")
    if config.remote:
        cmd.append("--remote")
    if config.remote_fallback:
        cmd.append("--remote-fallback")
    if config.timeout is not None:
        cmd.extend(["--timeout", str(config.timeout)])
    return cmd


def source_row_to_candidate_score(row: Mapping[str, Any]):
    from .source_shape import CandidateScore

    candidate_pcdump_error = _candidate_pcdump_error(row)
    return CandidateScore(
        candidate_id=str(row.get("candidate_id") or ""),
        compile_ok=(
            row.get("score_error_kind") != "infrastructure"
            and row.get("score_returncode") in (None, 0)
            and not candidate_pcdump_error
        ),
        checkdiff_pct=_float_or_none(
            row.get("checkdiff_pct")
            or row.get("checkdiff_match_percent")
            or row.get("match_percent")
        ),
        checkdiff_delta=_float_or_none(row.get("checkdiff_delta")),
        pcdump_score_delta=None,
        diagnostics_path=None,
        status=_row_status(row),
        score_reason=str(row.get("error")) if row.get("error") else None,
        candidate_size=int(row.get("candidate_size") or 0),
        helper_param_count=int(row.get("helper_param_count") or 0),
        checkdiff_baseline_pct=_float_or_none(row.get("checkdiff_baseline_pct")),
        score=_int_or_none(row.get("score")),
        target_score=_mapping_or_none(row.get("target_score")),
        expression_score=_mapping_or_none(row.get("expression_score")),
        structural_guard=_mapping_or_none(row.get("structural_guard")),
        structural_guard_error=(
            str(row.get("structural_guard_error"))
            if row.get("structural_guard_error") is not None
            else None
        ),
        checkdiff_evidence=_mapping_or_none(row.get("checkdiff_evidence")),
        source_file=_str_or_none(row.get("source_file")),
        source_retained=_str_or_none(row.get("source_retained")),
        pcdump_path=_str_or_none(row.get("pcdump_path")),
        score_command=_str_or_none(row.get("score_command")),
        score_returncode=_int_or_none(row.get("score_returncode")),
        score_stderr=_str_or_none(row.get("score_stderr")),
        error=_str_or_none(row.get("error")),
        score_error_kind=_str_or_none(row.get("score_error_kind")),
        terminal_safe=(
            bool(row.get("terminal_safe"))
            if row.get("terminal_safe") is not None
            else None
        ),
        full_unit_source=bool(row.get("full_unit_source")),
        target_matched=_int_or_none(row.get("target_matched")),
        target_targeted=_int_or_none(row.get("target_targeted")),
        target_virtual_distance=_int_or_none(row.get("target_virtual_distance")),
        expression_matched=_int_or_none(row.get("expression_matched")),
        expression_targeted=_int_or_none(row.get("expression_targeted")),
        expression_virtual_distance=_int_or_none(
            row.get("expression_virtual_distance")
        ),
        blockers=tuple(
            dict(item) for item in row.get("blockers") or []
            if isinstance(item, Mapping)
        ),
        source_hunks=tuple(
            dict(item) for item in row.get("source_hunks") or []
            if isinstance(item, Mapping)
        ),
    )


def _score_source_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    package_tools_path = str(Path(__file__).resolve().parents[2])
    repo_tools_path = str((repo_root / "tools" / "melee-agent").resolve())
    pythonpath_entries = [package_tools_path]
    if repo_tools_path != package_tools_path:
        pythonpath_entries.append(repo_tools_path)
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        for entry in existing_pythonpath.split(os.pathsep):
            if entry and entry not in pythonpath_entries:
                pythonpath_entries.append(entry)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return env


def _parse_score_source_stdout(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
        if not isinstance(payload, dict):
            return {
                "error": "score-source-json-not-object",
                "raw_stdout": stdout,
            }
        return payload
    except json.JSONDecodeError:
        return {
            "error": "score-source-json-parse-error",
            "raw_stdout": stdout,
        }


def _finalize_score_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    candidate_id = out.get("candidate_id")
    _merge_metric(out, "target", out.get("target_score"))
    _merge_metric(out, "expression", out.get("expression_score"))
    blockers = _normalized_blockers(out.get("blockers"), candidate_id=candidate_id)
    error = _str_or_none(out.get("error"))
    if error:
        infrastructure_error = _is_infrastructure_error(error, out)
        if error.lower() == "pcdump missing" and _candidate_compile_error(out):
            infrastructure_error = False
        out["score_error_kind"] = (
            "infrastructure"
            if infrastructure_error
            else "candidate"
        )
        _append_blocker(
            blockers,
            f"score-source-error:{error}",
            candidate_id=candidate_id,
        )
    if _pcdump_missing(out):
        out["score_error_kind"] = (
            "candidate" if _candidate_compile_error(out) else "infrastructure"
        )
        _append_blocker(
            blockers,
            "score-source-pcdump-missing",
            candidate_id=candidate_id,
        )
    if _structural_guard_rejected(out.get("structural_guard")):
        _append_blocker(
            blockers,
            f"structural-guard:{_structural_guard_reason(out.get('structural_guard'))}",
            candidate_id=candidate_id,
        )
    if (
        not error
        and not _row_has_target_or_expression_progress(out)
        and (
            out.get("target_targeted") is not None
            or out.get("expression_targeted") is not None
        )
    ):
        _append_blocker(
            blockers,
            "no-target-or-expression-improvement",
            candidate_id=candidate_id,
        )
    out["blockers"] = blockers
    out["terminal_safe"] = _is_terminal_safe_score_row(out)
    out["status"] = _row_status(out)
    if out.get("error") and not out.get("score_reason"):
        out["score_reason"] = str(out["error"])
    return out


def _is_terminal_safe_score_row(row: Mapping[str, Any]) -> bool:
    explicit = row.get("terminal_safe")
    if explicit is True and row.get("score_error_kind") != "infrastructure":
        return True
    if row.get("score_error_kind") == "infrastructure":
        return False
    if row.get("score_error_kind") == "candidate":
        return _candidate_error_terminal_safe(row)
    if row.get("error"):
        return False
    if _pcdump_missing(row):
        return False
    if row.get("score_returncode") not in (None, 0):
        return False
    return (
        isinstance(row.get("target_score"), Mapping)
        or isinstance(row.get("expression_score"), Mapping)
        or isinstance(row.get("structural_guard"), Mapping)
        or _float_or_none(row.get("checkdiff_match_percent")) is not None
        or _float_or_none(row.get("match_percent")) is not None
    )


def _candidate_error_terminal_safe(row: Mapping[str, Any]) -> bool:
    error = str(row.get("error") or "").lower()
    if error == "pcdump missing" and _candidate_compile_error(row):
        return True
    if not row.get("pcdump_path"):
        return False
    return "not in compiled pcdump" in error


def _candidate_pcdump_error(row: Mapping[str, Any]) -> bool:
    """Return true when the candidate compiled no usable target pcdump."""

    error = str(row.get("error") or "").lower()
    return (
        _pcdump_missing(row)
        or error == "pcdump missing"
        or "not in compiled pcdump" in error
    )


def _candidate_compile_error(row: Mapping[str, Any]) -> bool:
    text = "\n".join(
        str(row.get(key) or "")
        for key in ("stdout_tail", "stderr_tail", "score_stdout", "score_stderr")
    ).lower()
    return "mwcceppc_debug.exe compiler" in text and "error:" in text


def _is_infrastructure_error(error: str, row: Mapping[str, Any]) -> bool:
    if row.get("unsafe_local_pcdump_lane") is not None:
        return True
    if row.get("score_returncode") not in (None, 0):
        return True
    lowered = error.lower()
    return (
        lowered
        in {
            "score-source-interrupted",
            "score-source-timeout",
            "score-source-json-not-object",
            "score-source-json-parse-error",
            "candidate-path-missing",
            "pcdump missing",
            "unsafe local pcdump lane",
            "remote pcdump failed",
        }
        or lowered.startswith("score-source exited")
        or "timed out" in lowered
    )


def _pcdump_missing(row: Mapping[str, Any]) -> bool:
    if row.get("pcdump_path"):
        return False
    if row.get("error") in {"score-source-interrupted", "score-source-timeout"}:
        return False
    return (
        row.get("score_returncode") in (None, 0)
        and (
            isinstance(row.get("target_score"), Mapping)
            or isinstance(row.get("expression_score"), Mapping)
        )
    )


def _merge_metric(out: dict[str, Any], prefix: str, score: Any) -> None:
    if not isinstance(score, Mapping):
        return
    for field in ("matched", "targeted", "virtual_distance"):
        key = f"{prefix}_{field}"
        if out.get(key) is None:
            out[key] = _int_or_none(score.get(field))


def _row_has_target_or_expression_progress(row: Mapping[str, Any]) -> bool:
    for key in (
        "target_delta_matched",
        "expression_delta_matched",
        "target_matched",
        "expression_matched",
    ):
        value = _int_or_none(row.get(key))
        if value is not None and value > 0:
            return True
    return False


def _structural_guard_rejected(guard: Any) -> bool:
    return isinstance(guard, Mapping) and guard.get("accepted") is False


def _structural_guard_reason(guard: Any) -> str:
    if not isinstance(guard, Mapping):
        return "rejected"
    for key in ("classification_primary", "rejection_reason", "reason"):
        value = guard.get(key)
        if value:
            return str(value)
    classification = guard.get("classification")
    if isinstance(classification, Mapping) and classification.get("primary"):
        return str(classification["primary"])
    return "rejected"


def _row_status(row: Mapping[str, Any]) -> str:
    if row.get("score_error_kind") == "infrastructure":
        return "failed"
    if row.get("error"):
        return "score_error"
    targeted = _int_or_none(row.get("target_targeted")) or 0
    matched = _int_or_none(row.get("target_matched")) or 0
    if targeted > 0 and matched >= targeted:
        return "target_match"
    if _row_has_target_or_expression_progress(row):
        return "improved"
    checkdiff_delta = _float_or_none(row.get("checkdiff_delta"))
    if checkdiff_delta is not None and checkdiff_delta > 0:
        return "improved"
    return "no_match"


def _normalized_blockers(raw: Any, *, candidate_id: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for item in raw:
            if isinstance(item, Mapping):
                blocker = dict(item)
                blocker.setdefault("candidate_id", candidate_id)
                blockers.append(blocker)
            elif item:
                blockers.append({"reason": str(item), "candidate_id": candidate_id})
    elif raw:
        blockers.append({"reason": str(raw), "candidate_id": candidate_id})
    return blockers


def _append_blocker(
    blockers: list[dict[str, Any]],
    reason: str,
    *,
    candidate_id: Any,
) -> None:
    item = {"reason": reason, "candidate_id": candidate_id}
    if item not in blockers:
        blockers.append(item)


def _candidate_id(
    candidate: SourceCandidate | Mapping[str, Any],
    *,
    fallback: str,
) -> str:
    if isinstance(candidate, SourceCandidate):
        return candidate.candidate_id
    value = candidate.get("candidate_id")
    return str(value) if value else fallback


def _candidate_source_text(candidate: SourceCandidate | Mapping[str, Any]) -> str:
    if isinstance(candidate, SourceCandidate):
        return candidate.source_text
    value = candidate.get("source_text")
    if value is None:
        value = candidate.get("patched_source")
    return str(value or "")


def _candidate_summary(candidate: SourceCandidate | Mapping[str, Any]) -> str:
    if isinstance(candidate, SourceCandidate):
        return candidate.summary
    return str(candidate.get("summary") or "")


def _candidate_metadata(
    candidate: SourceCandidate | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(candidate, SourceCandidate):
        metadata = dict(candidate.metadata)
    else:
        raw = candidate.get("metadata")
        metadata = dict(raw) if isinstance(raw, Mapping) else {}
        for key, value in candidate.items():
            if key not in {
                "candidate_id",
                "source_text",
                "patched_source",
                "summary",
                "source_hunks",
                "metadata",
            } and key not in metadata:
                metadata[key] = value
    return metadata


def _candidate_source_hunks(
    candidate: SourceCandidate | Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = (
        candidate.source_hunks
        if isinstance(candidate, SourceCandidate)
        else candidate.get("source_hunks", ())
    )
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _row_candidate_path(row: Mapping[str, Any]) -> Path | None:
    value = row.get("source_file") or row.get("source_retained") or row.get(
        "candidate_path"
    )
    if not value:
        return None
    return Path(str(value))


def _unique_safe_name(candidate_id: str, used_names: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate_id).strip("._")
    if not base:
        base = "candidate"
    name = base
    suffix = 2
    while name in used_names:
        name = f"{base}_{suffix}"
        suffix += 1
    used_names.add(name)
    return name


def _timeout_stream_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
