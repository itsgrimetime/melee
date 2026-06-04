#!/usr/bin/env python3
"""Generate function mismatch taxonomy artifacts from report.json + checkdiff."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
MELEE_AGENT_ROOT = REPO_ROOT / "tools" / "melee-agent"
if str(MELEE_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(MELEE_AGENT_ROOT))

from src.mwcc_debug.frame_taxonomy import classify_frame_taxonomy

DEFAULT_REPORT = REPO_ROOT / "build" / "GALE01" / "report.json"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "function-taxonomy"
_DECL_ORDER_EVAL_LOCK = threading.Lock()

BUCKET_ORDER = [
    "signature-call-type",
    "inline-boundary",
    "structural-reconstruction",
    "data-symbol-relocation",
    "stack-local-layout",
    "indexed-struct-pointer",
    "known-small-pattern-candidate",
    "register-allocator",
]

TIER_ORDER = [">=99%", "97-99%", "95-97%", "90-95%", "<90%"]


@dataclass(frozen=True)
class FunctionCandidate:
    function: str
    unit: str
    file_path: str
    size_bytes: int
    match_percent: float
    address: str
    object_status: str


@dataclass(frozen=True)
class InventoryResult:
    report_non100_count: int
    attempted_count: int
    classified_count: int
    error_count: int
    output_dir: Path


CheckdiffRunner = Callable[[str], tuple[int, str, str]]
DeclOrderEvaluator = Callable[[FunctionCandidate, dict[str, Any]], dict[str, Any]]
FrameReportRunner = Callable[[FunctionCandidate], dict[str, Any] | None]
CastAuditRunner = Callable[[FunctionCandidate], dict[str, Any]]


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def strip_src_prefix(path: str) -> str:
    return path[4:] if path.startswith("src/") else path


def format_address(value: Any) -> str:
    try:
        return f"0x{int(value):08x}"
    except (TypeError, ValueError):
        return ""


def match_tier(match_percent: float) -> str:
    if match_percent >= 99:
        return ">=99%"
    if match_percent >= 97:
        return "97-99%"
    if match_percent >= 95:
        return "95-97%"
    if match_percent >= 90:
        return "90-95%"
    return "<90%"


def load_report_candidates(report_path: Path) -> list[FunctionCandidate]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidates: list[FunctionCandidate] = []

    for unit in report.get("units", []):
        unit_name = unit.get("name", "")
        metadata = unit.get("metadata") or {}
        file_path = strip_src_prefix(metadata.get("source_path") or unit_name)
        object_status = "Matching" if metadata.get("complete") else "NonMatching"
        for func in unit.get("functions") or []:
            match_percent = parse_float(func.get("fuzzy_match_percent"), 100.0)
            if match_percent >= 100:
                continue
            func_metadata = func.get("metadata") or {}
            candidates.append(
                FunctionCandidate(
                    function=func.get("name", ""),
                    unit=unit_name,
                    file_path=file_path,
                    size_bytes=parse_int(func.get("size")),
                    match_percent=match_percent,
                    address=format_address(func_metadata.get("virtual_address")),
                    object_status=object_status,
                )
            )
    return candidates


def default_checkdiff_runner(function: str) -> tuple[int, str, str]:
    cmd = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
        "--no-build",
        "--no-name-magic",
        "--no-fingerprint",
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def parse_checkdiff_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("checkdiff produced no JSON output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start >= 0:
            return json.loads(text[start:])
        raise


def parse_json_object(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("command produced no JSON output")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        parsed = json.loads(text[start:])
    if not isinstance(parsed, dict):
        raise ValueError("command JSON output was not an object")
    return parsed


def is_known_small_candidate(candidate: FunctionCandidate, payload: dict[str, Any]) -> bool:
    classification = payload.get("classification") or {}
    primary = classification.get("primary")
    structural = payload.get("structural") or {}
    opcode_similarity = parse_float(structural.get("opcode_similarity"))
    line_delta = abs(parse_int(structural.get("line_delta")))

    if primary == "operand-register-or-offset":
        return True
    if primary != "instruction-sequence":
        return False
    return (
        candidate.match_percent >= 97
        and candidate.size_bytes <= 500
        and opcode_similarity >= 0.995
        and line_delta <= 1
    )


def _stack_frame_missing_bytes(classification: dict[str, Any]) -> int | None:
    delta = classification.get("stack_frame_delta")
    if not isinstance(delta, dict):
        return None
    missing = delta.get("missing_stack_bytes")
    if isinstance(missing, int) and not isinstance(missing, bool):
        return missing
    expected = delta.get("expected_frame_size")
    current = delta.get("current_frame_size")
    if (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and isinstance(current, int)
        and not isinstance(current, bool)
    ):
        return expected - current
    return None


def _signature_residual_bucket(
    candidate: FunctionCandidate, payload: dict[str, Any]
) -> tuple[str, str, bool]:
    classification = payload.get("classification") or {}
    reasons = classification.get("reasons") or []
    reason_text = "\n".join(str(reason).lower() for reason in reasons)
    structural = payload.get("structural") or {}
    line_delta = abs(parse_int(structural.get("line_delta")))
    missing = _stack_frame_missing_bytes(classification)

    if missing == 0:
        return "stack-local-layout", "same-frame-stack-slot-placement", False
    if (
        classification.get("stack_frame_delta")
        or "frame reservation gap" in reason_text
        or "pad_stack" in reason_text
    ):
        if missing is not None and missing > 0:
            return "stack-local-layout", "frame-too-small", False
        if missing is not None and missing < 0:
            return "stack-local-layout", "frame-too-large", False
        if "too small" in reason_text:
            return "stack-local-layout", "frame-too-small", False
        if "too large" in reason_text or "extra_stack_bytes" in reason_text:
            return "stack-local-layout", "frame-too-large", False
        return "stack-local-layout", "frame-size-delta", False
    if "stack slot" in reason_text:
        return "stack-local-layout", "same-frame-stack-slot-placement", False
    if (
        "relocation" in reason_text
        or "data/symbol" in reason_text
        or "name-magic" in reason_text
        or "sdata" in reason_text
    ):
        return "data-symbol-relocation", "signature-red-herring-data-symbol", False
    if "inline" in reason_text:
        return "inline-boundary", "signature-red-herring-inline-boundary", False
    if line_delta > 1:
        return "structural-reconstruction", "branch-or-control-flow-shape", False
    return "structural-reconstruction", "opcode-sequence-diff", False


def classify_bucket(
    candidate: FunctionCandidate,
    payload: dict[str, Any],
    *,
    cast_audit: dict[str, Any] | None = None,
) -> tuple[str, str, bool]:
    classification = payload.get("classification") or {}
    primary = classification.get("primary") or "unknown"
    reasons = classification.get("reasons") or []
    reason_text = "\n".join(str(reason).lower() for reason in reasons)

    if primary == "signature-type-mismatch":
        if parse_int((cast_audit or {}).get("medium_plus_count")) <= 0:
            return _signature_residual_bucket(candidate, payload)
        return "signature-call-type", "call-shape-or-prototype", False
    if primary == "inline-boundary-toolchain-artifact":
        return "inline-boundary", "missing-reference-call-current-inlined", False
    if primary == "data-symbol-or-relocation":
        return "data-symbol-relocation", "persistent-data-symbol-or-relocation", False
    if primary == "indexed-struct-pointer-materialization":
        return "indexed-struct-pointer", "array-indexed-vs-element-pointer", False
    if primary == "stack-slot-layout":
        return "stack-local-layout", "same-frame-stack-slot-placement", False
    if primary == "stack-layout":
        missing = _stack_frame_missing_bytes(classification)
        if missing == 0:
            return "stack-local-layout", "same-frame-stack-slot-placement", False
        if "frame reservation gap" in reason_text or "pad_stack" in reason_text:
            if missing is not None and missing > 0:
                return "stack-local-layout", "frame-too-small", False
            if missing is not None and missing < 0:
                return "stack-local-layout", "frame-too-large", False
            if "too small" in reason_text:
                return "stack-local-layout", "frame-too-small", False
            if "too large" in reason_text:
                return "stack-local-layout", "frame-too-large", False
            return "stack-local-layout", "frame-size-delta", False
        return "stack-local-layout", "frame-size-delta", False
    if primary == "register-allocation":
        if "hsd_assert" in reason_text or "assert" in reason_text:
            return "register-allocator", "register-plus-hsd-assert-data", False
        return "register-allocator", "register-only-needs-pcdump-proof", False
    if is_known_small_candidate(candidate, payload):
        return "known-small-pattern-candidate", "small-opcode-or-operand-pattern", True
    if primary == "control-flow-source-shape":
        return "structural-reconstruction", "branch-or-control-flow-shape", False
    if primary == "instruction-sequence":
        return "structural-reconstruction", "opcode-sequence-diff", False
    if primary == "operand-register-or-offset":
        return "known-small-pattern-candidate", "operand-register-offset-small", True
    return "structural-reconstruction", "direct-inspection-needed", False


def describe_actionability(
    bucket: str,
    subcategory: str,
    *,
    frame_taxonomy: dict[str, Any] | None = None,
) -> dict[str, str]:
    if bucket == "stack-local-layout" and frame_taxonomy is not None:
        tier = str(frame_taxonomy.get("closability_tier") or "")
        cause = str(frame_taxonomy.get("cause") or "stack-frame-divergence")
        if tier == "current-tools-padstack":
            return {
                "source_actionability": "current-tools",
                "headline_tool": "frame-transform-search",
                "actionability_reason": (
                    f"{cause}; current frame-reservation probes can test this "
                    "without committing a source padding edit"
                ),
            }
        if tier == "reorder-gated-362":
            return {
                "source_actionability": "generator-gated",
                "headline_tool": "lifetime-layout",
                "actionability_reason": (
                    f"{cause}; needs the #362 lifetime/reorder source lever "
                    "before it can be closed by current tooling"
                ),
            }
        if tier == "gen-gated-366":
            return {
                "source_actionability": "generator-gated",
                "headline_tool": "frame-transform-search",
                "actionability_reason": (
                    f"{cause}; needs the #366 directed frame-transform "
                    "generator path before it is a bounded source fix"
                ),
            }
        if tier == "ceiling":
            return {
                "source_actionability": "ceiling",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    f"{cause}; current evidence marks this as a ceiling or "
                    "unresolved compiler-layout boundary"
                ),
            }
    if bucket == "stack-local-layout":
        if subcategory == "same-frame-stack-slot-placement":
            return {
                "source_actionability": "source-probe",
                "headline_tool": "lifetime-layout",
                "actionability_reason": (
                    "same-frame stack-slot placement can be tested with "
                    "lifetime-layout and decl-order probes"
                ),
            }
        if subcategory in {"frame-too-small", "frame-too-large", "frame-size-delta"}:
            return {
                "source_actionability": "diagnostic-only",
                "headline_tool": "frame-reservations",
                "actionability_reason": (
                    "frame-size residual; inspect the frame model, but no bounded "
                    "source transform is available yet"
                ),
            }
    if bucket == "known-small-pattern-candidate":
        return {
            "source_actionability": "current-tools-small-pattern",
            "headline_tool": "mismatch-db",
            "actionability_reason": "small operand/opcode pattern likely has a targeted source edit",
        }
    if bucket == "signature-call-type":
        return {
            "source_actionability": "current-tools-signature",
            "headline_tool": "debug-suggest-casts",
            "actionability_reason": (
                "call shape or prototype mismatch; inspect casts, typedef widths, "
                "and declarations with current signature tools"
            ),
        }
    if bucket == "inline-boundary":
        return {
            "source_actionability": "current-tools-inline",
            "headline_tool": "patterns-inlines",
            "actionability_reason": (
                "inline/call boundary mismatch; compare helper definitions and "
                "call-preserving source forms"
            ),
        }
    if bucket == "data-symbol-relocation":
        return {
            "source_actionability": "current-tools-data-symbol",
            "headline_tool": "checkdiff-name-magic",
            "actionability_reason": (
                "data, string, or relocation mismatch; model named data and "
                "rerun checkdiff with relocation/name-magic evidence"
            ),
        }
    if bucket == "indexed-struct-pointer":
        return {
            "source_actionability": "current-tools-indexed-pointer",
            "headline_tool": "source-shape",
            "actionability_reason": (
                "array-indexed versus element-pointer source shape mismatch; "
                "try pointer temporary and indexed-access rewrites"
            ),
        }
    if bucket == "register-allocator":
        return {
            "source_actionability": "pcdump-proof-needed",
            "headline_tool": "mwcc-debug",
            "actionability_reason": (
                "instruction stream is close; collect pcdump-backed allocator "
                "evidence before source edits"
            ),
        }
    if bucket == "structural-reconstruction":
        if subcategory == "branch-or-control-flow-shape":
            return {
                "source_actionability": "structural-rebuild",
                "headline_tool": "control-flow-shape-search",
                "actionability_reason": (
                    "control-flow/source-shape mismatch; rebuild natural branch "
                    "or loop structure before local tuning"
                ),
            }
        if subcategory == "opcode-sequence-diff":
            return {
                "source_actionability": "opcode-reconstruction",
                "headline_tool": "opseq-mismatch-db",
                "actionability_reason": (
                    "generic opcode sequence mismatch; search similar opcode "
                    "patterns and matched functions for source shape"
                ),
            }
        if subcategory == "direct-inspection-needed":
            return {
                "source_actionability": "backend-ceiling",
                "headline_tool": "manual-inspection",
                "actionability_reason": (
                    "backend-ceiling classification; inspect manually and bank "
                    "when no current source lever is credible"
                ),
            }
    return {
        "source_actionability": "source-probe",
        "headline_tool": bucket,
        "actionability_reason": "heuristic taxonomy bucket has source-inspection next steps",
    }


def next_command(bucket: str, subcategory: str, candidate: FunctionCandidate) -> str:
    function = candidate.function
    source_path = f"src/{candidate.file_path}"
    if bucket == "signature-call-type":
        return (
            f"melee-agent debug suggest casts {function} && "
            f"python tools/checkdiff.py {function} --compact"
        )
    if bucket == "inline-boundary":
        return (
            f"python tools/checkdiff.py {function} --compact && "
            f"melee-agent patterns inlines {source_path}"
        )
    if bucket == "structural-reconstruction":
        if subcategory == "branch-or-control-flow-shape":
            return (
                f"melee-agent debug mutate control-flow-shape-search -f {function} "
                f"--source-file {source_path} --compile-probes --json"
            )
        return (
            f"melee-agent extract get {function} && "
            f"python tools/checkdiff.py {function} --compact"
        )
    if bucket == "data-symbol-relocation":
        return f"python tools/checkdiff.py {function} --compact --no-name-magic"
    if bucket == "stack-local-layout":
        if subcategory == "same-frame-stack-slot-placement":
            return (
                f"python tools/checkdiff.py {function} --compact --pcdump <pcdump-if-available> && "
                f"melee-agent debug mutate lifetime-layout -f {function} --compile-probes"
            )
        return (
            f"melee-agent debug inspect frame-reservations -f {function} && "
            f"melee-agent debug suggest frame -f {function}"
        )
    if bucket == "known-small-pattern-candidate":
        return (
            f"python tools/checkdiff.py {function} --compact && "
            "melee-agent mismatch search '<opcode/type clue>'"
        )
    if bucket == "register-allocator":
        return (
            "melee-agent debug dump setup && "
            f"melee-agent debug dump local {source_path} --function {function}"
        )
    return f"python tools/checkdiff.py {function} --compact"


def default_frame_report_runner(
    candidate: FunctionCandidate,
) -> dict[str, Any] | None:
    cmd = [
        "melee-agent",
        "debug",
        "inspect",
        "frame-reservations",
        "-f",
        candidate.function,
        "--json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return parse_json_object(proc.stdout)
    except Exception:
        return None


def default_cast_audit_runner(candidate: FunctionCandidate) -> dict[str, Any]:
    source_path = REPO_ROOT / "src" / candidate.file_path
    if not source_path.exists():
        return {
            "status": "source-missing",
            "medium_plus_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
        }
    try:
        from src.mwcc_debug.cast_audit import audit_function_casts

        warnings = audit_function_casts(
            source_path.read_text(encoding="utf-8"),
            candidate.function,
        )
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "medium_plus_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
        }
    high_count = sum(1 for warning in warnings if warning.severity == "high")
    medium_count = sum(1 for warning in warnings if warning.severity == "medium")
    low_count = sum(1 for warning in warnings if warning.severity == "low")
    return {
        "status": "ok",
        "medium_plus_count": high_count + medium_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
    }


def frame_taxonomy_for_candidate(
    candidate: FunctionCandidate,
    classification: dict[str, Any],
    bucket: str,
    frame_report_runner: FrameReportRunner | None,
) -> dict[str, Any] | None:
    if bucket != "stack-local-layout":
        return None
    frame_report = None
    if frame_report_runner is not None:
        try:
            frame_report = frame_report_runner(candidate)
        except Exception:
            frame_report = None
    return classify_frame_taxonomy(
        candidate.function,
        classification=classification,
        source_path=f"src/{candidate.file_path}",
        frame_report=frame_report,
    )


def attach_frame_taxonomy(
    record: dict[str, Any],
    frame_taxonomy: dict[str, Any],
) -> None:
    record["frame_taxonomy"] = frame_taxonomy
    record["frame_cause"] = frame_taxonomy.get("cause")
    record["frame_raw_cause"] = frame_taxonomy.get("raw_cause")
    record["frame_verdict"] = frame_taxonomy.get("verdict")
    record["frame_raw_verdict"] = frame_taxonomy.get("raw_verdict")
    record["frame_closability_tier"] = frame_taxonomy.get("closability_tier")
    record["frame_attribution_status"] = frame_taxonomy.get("attribution_status")
    record["frame_source_object"] = frame_taxonomy.get("source_object")
    record["frame_source_object_symbol"] = frame_taxonomy.get("source_object_symbol")
    record["frame_next_command"] = frame_taxonomy.get("next_command")
    record["frame_reason"] = frame_taxonomy.get("reason")
    if frame_taxonomy.get("next_command"):
        record["next_command"] = frame_taxonomy["next_command"]


def default_decl_order_evaluator(
    candidate: FunctionCandidate,
    _record: dict[str, Any],
) -> dict[str, Any]:
    cmd = [
        "melee-agent",
        "debug",
        "mutate",
        "decl-orders",
        candidate.function,
        "--strategy",
        "all",
        "--json",
    ]
    with _DECL_ORDER_EVAL_LOCK:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
    if proc.returncode != 0:
        return {
            "evaluated_status": "unevaluated: decl-orders command failed",
            "candidate_count": 0,
            "best_decl_delta": None,
            "best_ordering": "",
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }
    try:
        payload = parse_json_object(proc.stdout)
    except Exception as exc:
        status = "unevaluated: decl-orders emitted no JSON"
        if "no candidate orderings" in proc.stdout.lower():
            status = "no-candidates"
        return {
            "evaluated_status": status,
            "candidate_count": 0,
            "best_decl_delta": None,
            "best_ordering": "",
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:] or str(exc),
        }
    return summarize_decl_order_payload(payload)


def summarize_decl_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rounds = payload.get("rounds") or []
    results: list[dict[str, Any]] = []
    for round_payload in rounds:
        for result in round_payload.get("results") or []:
            if isinstance(result, dict):
                results.append(result)
    candidate_count = len(results)
    skipped = [result for result in results if result.get("skipped")]
    scored = [
        result for result in results
        if result.get("match_pct") is not None and result.get("delta") is not None
    ]
    best_result = max(
        scored,
        key=lambda row: parse_float(row.get("delta")),
        default=None,
    )
    best_delta = (
        parse_float(best_result.get("delta"))
        if best_result is not None
        else None
    )
    best_ordering = str(best_result.get("label") or "") if best_result else ""
    if candidate_count == 0:
        status = "no-candidates"
    elif scored:
        status = "evaluated"
    elif skipped and len(skipped) == candidate_count:
        reasons = " ".join(str(item.get("skip_reason") or "") for item in skipped)
        status = (
            "no-freedom-init-dependency"
            if "depends on" in reasons
            else "unevaluated: all candidates skipped"
        )
    else:
        status = "unevaluated: no scored candidates"
    return {
        "evaluated_status": status,
        "candidate_count": candidate_count,
        "evaluated_candidate_count": len(scored),
        "skipped_count": len(skipped),
        "best_decl_delta": best_delta,
        "best_ordering": best_ordering,
        "baseline_pct": payload.get("baseline_pct"),
        "best_pct": payload.get("best_pct"),
        "scope": payload.get("scope", ""),
        "selected_scope_reason": payload.get("selected_scope_reason", ""),
    }


def should_evaluate_decl_orders(
    candidate: FunctionCandidate,
    bucket: str,
    subcategory: str,
) -> bool:
    return (
        bucket == "stack-local-layout"
        and subcategory == "same-frame-stack-slot-placement"
        and candidate.match_percent >= 99.0
    )


def attach_decl_order_summary(
    record: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    record["decl_order_summary"] = summary
    record["decl_order_evaluated_status"] = summary.get("evaluated_status", "")
    record["decl_order_candidate_count"] = summary.get("candidate_count", 0)
    record["decl_order_best_delta"] = summary.get("best_decl_delta")
    record["decl_order_best_ordering"] = summary.get("best_ordering", "")


def classify_candidate(
    candidate: FunctionCandidate,
    runner: CheckdiffRunner,
    decl_order_evaluator: DeclOrderEvaluator | None = default_decl_order_evaluator,
    frame_report_runner: FrameReportRunner | None = default_frame_report_runner,
    cast_audit_runner: CastAuditRunner | None = default_cast_audit_runner,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    started = time.perf_counter()
    returncode, stdout, stderr = runner(candidate.function)
    elapsed = time.perf_counter() - started
    try:
        payload = parse_checkdiff_stdout(stdout)
    except Exception as exc:
        return None, {
            "function": candidate.function,
            "error": "json_decode",
            "file_path": candidate.file_path,
            "message": stderr.strip() or str(exc),
            "returncode": returncode,
            "stdout_tail": stdout[-1000:],
            "stderr_tail": stderr[-1000:],
        }

    classification = payload.get("classification") or {}
    primary = classification.get("primary") or "unknown"
    cast_audit = None
    if primary == "signature-type-mismatch" and cast_audit_runner is not None:
        try:
            cast_audit = cast_audit_runner(candidate)
        except Exception as exc:
            cast_audit = {
                "status": "error",
                "message": str(exc),
                "medium_plus_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            }
    bucket, subcategory, known_small = classify_bucket(
        candidate,
        payload,
        cast_audit=cast_audit,
    )
    frame_taxonomy = frame_taxonomy_for_candidate(
        candidate,
        classification,
        bucket,
        frame_report_runner,
    )
    actionability = describe_actionability(
        bucket,
        subcategory,
        frame_taxonomy=frame_taxonomy,
    )
    record = {
        "ok": True,
        "function": candidate.function,
        "address": candidate.address,
        "file_path": candidate.file_path,
        "object_status": candidate.object_status,
        "size_bytes": candidate.size_bytes,
        "match": candidate.match_percent / 100.0,
        "match_percent": candidate.match_percent,
        "match_tier": match_tier(candidate.match_percent),
        "effective_match": False,
        "classification": classification,
        "primary": primary,
        "reasons": classification.get("reasons") or [],
        "structural": payload.get("structural") or {},
        "reference_lines": payload.get("reference_lines"),
        "current_lines": payload.get("current_lines"),
        "work_bucket": bucket,
        "subcategory": subcategory,
        "known_small_pattern_candidate": known_small,
        "cast_audit": cast_audit,
        "cast_audit_status": (cast_audit or {}).get("status"),
        "cast_medium_plus_count": parse_int((cast_audit or {}).get("medium_plus_count")),
        **actionability,
        "confidence": "heuristic",
        "elapsed_sec": round(elapsed, 3),
        "stderr_tail": stderr[-1000:],
        "next_command": next_command(bucket, subcategory, candidate),
    }
    if frame_taxonomy is not None:
        attach_frame_taxonomy(record, frame_taxonomy)
    if (
        decl_order_evaluator is not None
        and should_evaluate_decl_orders(candidate, bucket, subcategory)
    ):
        attach_decl_order_summary(record, decl_order_evaluator(candidate, record))
    return record, None


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "match_percent",
        "function",
        "work_bucket",
        "primary",
        "subcategory",
        "frame_cause",
        "frame_verdict",
        "frame_closability_tier",
        "frame_attribution_status",
        "frame_source_object_symbol",
        "cast_audit_status",
        "cast_medium_plus_count",
        "source_actionability",
        "headline_tool",
        "actionability_reason",
        "file_path",
        "size_bytes",
        "next_command",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_queue(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "match_percent",
        "function",
        "primary",
        "subcategory",
        "frame_cause",
        "frame_verdict",
        "frame_closability_tier",
        "frame_attribution_status",
        "frame_source_object_symbol",
        "cast_audit_status",
        "cast_medium_plus_count",
        "source_actionability",
        "headline_tool",
        "actionability_reason",
        "decl_order_best_delta",
        "decl_order_best_ordering",
        "decl_order_evaluated_status",
        "decl_order_candidate_count",
        "file_path",
        "frame_next_command",
        "next_command",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["match_percent"] = f"{parse_float(row.get('match_percent')):.5f}"
            if row.get("decl_order_best_delta") is not None:
                out["decl_order_best_delta"] = (
                    f"{parse_float(row.get('decl_order_best_delta')):.5f}"
                )
            writer.writerow(out)


def write_error_queue(path: Path, errors: list[dict[str, Any]]) -> None:
    fields = ["function", "error", "file_path", "message"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(errors)


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def write_summary(
    path: Path,
    *,
    report_non100_count: int,
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    bucket_counts = count_by(records, "work_bucket")
    primary_counts = count_by(records, "primary")
    tier_counts = count_by(records, "match_tier")
    frame_closability_counts = count_by(
        [row for row in records if row.get("frame_closability_tier")],
        "frame_closability_tier",
    )

    lines = [
        "# Function Mismatch Taxonomy Inventory",
        "",
        "Generated from `build/GALE01/report.json` and a read-only `checkdiff --no-build --no-name-magic` pass.",
        "",
        "## Population",
        "| Population | Count |",
        "| --- | --- |",
        f"| Report non-100% | {report_non100_count} |",
        f"| Successfully classified by checkdiff | {len(records)} |",
        f"| Checkdiff extraction errors | {len(errors)} |",
        "| Report-only not extract-backed | 0 |",
        "| DB-completed/excluded extract-backed non-100% | 0 |",
        "",
        "## Work Buckets",
        "| Bucket | Count |",
        "| --- | --- |",
    ]
    for bucket in BUCKET_ORDER:
        lines.append(f"| {bucket} | {bucket_counts.get(bucket, 0)} |")
    lines.extend(["", "## Primary Checkdiff Classifications", "| Primary | Count |", "| --- | --- |"])
    for primary, count in sorted(primary_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {primary} | {count} |")
    lines.extend(["", "## Match Tiers", "| Tier | Classified |", "| --- | --- |"])
    for tier in TIER_ORDER:
        lines.append(f"| {tier} | {tier_counts.get(tier, 0)} |")
    if frame_closability_counts:
        lines.extend(
            [
                "",
                "## Stack Frame Closability",
                "| Closability tier | Classified |",
                "| --- | --- |",
            ]
        )
        for tier, count in sorted(frame_closability_counts.items()):
            lines.append(f"| {tier} | {count} |")
    lines.extend(["", "## High-ROI Queues"])
    for bucket in BUCKET_ORDER:
        lines.append(f"- `build/function-taxonomy/queues/{bucket}.tsv`")
    lines.extend(
        [
            "- `build/function-taxonomy/queues/checkdiff-errors.tsv`",
            "- `build/function-taxonomy/queues/report-only-not-extract-backed.tsv`",
            "- `build/function-taxonomy/queues/db-completed-extract-backed-non100.tsv`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_placeholder_auxiliary_files(output_dir: Path) -> None:
    write_jsonl(output_dir / "report-only-nonextract-backed.jsonl", [])
    write_jsonl(output_dir / "db-completed-extract-backed-non100.jsonl", [])
    queues = output_dir / "queues"
    for name in [
        "report-only-not-extract-backed.tsv",
        "db-completed-extract-backed-non100.tsv",
    ]:
        (queues / name).write_text("match_percent\tfunction\tfile_path\tobject_status\n", encoding="utf-8")


def generate_inventory(
    report_path: Path | str = DEFAULT_REPORT,
    output_dir: Path | str = DEFAULT_OUTPUT,
    *,
    checkdiff_runner: CheckdiffRunner = default_checkdiff_runner,
    decl_order_evaluator: DeclOrderEvaluator | None = default_decl_order_evaluator,
    frame_report_runner: FrameReportRunner | None = default_frame_report_runner,
    workers: int = 4,
    limit: int | None = None,
) -> InventoryResult:
    report_path = Path(report_path).resolve()
    output_dir = Path(output_dir).resolve()
    candidates = load_report_candidates(report_path)
    attempted = candidates[:limit] if limit is not None else candidates

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for record, error in executor.map(
            lambda candidate: classify_candidate(
                candidate,
                checkdiff_runner,
                decl_order_evaluator,
                frame_report_runner,
            ),
            attempted,
        ):
            if record is not None:
                records.append(record)
            if error is not None:
                errors.append(error)

    records.sort(key=lambda row: (-parse_float(row.get("match_percent")), row.get("function", "")))
    errors.sort(key=lambda row: row.get("function", ""))

    output_dir.mkdir(parents=True, exist_ok=True)
    queues = output_dir / "queues"
    queues.mkdir(exist_ok=True)

    write_jsonl(output_dir / "taxonomy.records.jsonl", records)
    write_csv(output_dir / "taxonomy.records.csv", records)
    write_jsonl(output_dir / "checkdiff-errors.jsonl", errors)
    write_placeholder_auxiliary_files(output_dir)

    for bucket in BUCKET_ORDER:
        bucket_rows = [row for row in records if row.get("work_bucket") == bucket]
        write_queue(queues / f"{bucket}.tsv", bucket_rows)
    write_error_queue(queues / "checkdiff-errors.tsv", errors)
    write_summary(
        output_dir / "summary.md",
        report_non100_count=len(candidates),
        records=records,
        errors=errors,
    )

    return InventoryResult(
        report_non100_count=len(candidates),
        attempted_count=len(attempted),
        classified_count=len(records),
        error_count=len(errors),
        output_dir=output_dir,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate function taxonomy JSONL/TSV artifacts from report.json."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Path to build/GALE01/report.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory for function-taxonomy artifacts.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent checkdiff subprocesses.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N non-100 report functions.",
    )
    parser.add_argument(
        "--skip-decl-order-eval",
        action="store_true",
        help="Skip bounded decl-orders evaluation for >=99%% stack-local-layout rows.",
    )
    parser.add_argument(
        "--skip-frame-report-attribution",
        action="store_true",
        help=(
            "Skip best-effort pcdump-backed frame-reservation attribution for "
            "stack-local-layout rows."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = generate_inventory(
            args.report,
            args.output,
            workers=args.workers,
            limit=args.limit,
            decl_order_evaluator=(
                None if args.skip_decl_order_eval else default_decl_order_evaluator
            ),
            frame_report_runner=(
                None
                if args.skip_frame_report_attribution
                else default_frame_report_runner
            ),
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Generated taxonomy artifacts in {result.output_dir}")
    print(
        "Rows: "
        f"{result.report_non100_count} report non-100, "
        f"{result.attempted_count} attempted, "
        f"{result.classified_count} classified, "
        f"{result.error_count} errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
