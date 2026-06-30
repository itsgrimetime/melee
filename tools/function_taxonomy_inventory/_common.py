#!/usr/bin/env python3
"""Generate function mismatch taxonomy artifacts from report.json + checkdiff."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
MELEE_AGENT_ROOT = REPO_ROOT / "tools" / "melee-agent"
if str(MELEE_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(MELEE_AGENT_ROOT))

import src.attempt_evidence as attempt_evidence
from src.attempt_evidence import (
    TERMINAL_ATTEMPT_FIELDS,
    apply_terminal_attempt_overlay,
    load_terminal_attempt_evidence,
)
from src.mwcc_debug.frame_taxonomy import classify_frame_taxonomy

DEFAULT_REPORT = REPO_ROOT / "build" / "GALE01" / "report.json"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "function-taxonomy"
DEFAULT_CHECKDIFF_TIMEOUT = 120.0
DEFAULT_DECL_ORDER_TIMEOUT = 180.0
DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT = 60.0
DEFAULT_STRUCT_VERIFY_TIMEOUT = 180.0
DEFAULT_PROGRESS_INTERVAL = 30.0
RUN_STATUS_FILENAME = "run-status.json"
RUN_STATUS_SCHEMA_VERSION = 1
_DECL_ORDER_EVAL_LOCK = threading.RLock()
NON_STRUCT_BASE_REGS = {"r1", "r2", "r13"}
DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS = {
    "no-name-magic-candidate": "blocked-data-symbol-no-name-magic-candidate",
    "unsupported-source-site": "blocked-data-symbol-unsupported-source-site",
    "ambiguous-relocation-pair": (
        "blocked-data-symbol-ambiguous-relocation-pair"
    ),
    "unsupported-reloc-kind": "blocked-data-symbol-unsupported-reloc-kind",
    "raw-diff-no-supported-data-symbol-pair": (
        "blocked-data-symbol-raw-diff-no-supported-data-symbol-pair"
    ),
    "no-name-magic-validation-failed": (
        "blocked-data-symbol-no-name-magic-validation-failed"
    ),
    "ambiguous-sdata2-value": "blocked-data-symbol-ambiguous-sdata2-value",
    "sdata2-pool-order-dependent": (
        "blocked-data-symbol-sdata2-pool-order-dependent"
    ),
}

BUCKET_ORDER = [
    "signature-call-type",
    "inline-boundary",
    "structural-reconstruction",
    "data-symbol-relocation",
    "stack-local-layout",
    "indexed-struct-pointer",
    "struct-offset-discrepancy",
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
NameMagicPreflightRunner = Callable[[FunctionCandidate], dict[str, Any] | None]
StructVerifyRunner = Callable[[FunctionCandidate, dict[str, Any]], dict[str, Any] | None]


def _tail_text(value: Any, limit: int = 1000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-limit:]
    return str(value)[-limit:]


def _format_timeout(timeout: Any) -> str:
    try:
        return f"{float(timeout):g}s"
    except (TypeError, ValueError):
        return "unknown timeout"


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


def _candidate_source_path(candidate: FunctionCandidate) -> Path | None:
    if not candidate.file_path:
        return None
    return REPO_ROOT / "src" / candidate.file_path


def _snapshot_candidate_source(candidate: FunctionCandidate) -> tuple[Path, str] | None:
    source_path = _candidate_source_path(candidate)
    if source_path is None:
        return None
    try:
        return source_path, source_path.read_text(encoding="utf-8")
    except OSError:
        return None


def _restore_candidate_source(snapshot: tuple[Path, str] | None) -> None:
    if snapshot is None:
        return
    source_path, original = snapshot
    source_path.write_text(original, encoding="utf-8")


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


def _unit_has_auditable_fuzzy_100(unit: dict[str, Any], metadata: dict[str, Any]) -> bool:
    if metadata.get("complete"):
        return False
    measures = unit.get("measures") or {}
    matched = parse_int(measures.get("matched_functions"), -1)
    total = parse_int(
        measures.get("total_functions", measures.get("functions")),
        -1,
    )
    return total > 0 and 0 <= matched < total


def load_report_candidates(report_path: Path) -> list[FunctionCandidate]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidates: list[FunctionCandidate] = []

    for unit in report.get("units", []):
        unit_name = unit.get("name", "")
        metadata = unit.get("metadata") or {}
        file_path = strip_src_prefix(metadata.get("source_path") or unit_name)
        object_status = "Matching" if metadata.get("complete") else "NonMatching"
        audit_fuzzy_100 = _unit_has_auditable_fuzzy_100(unit, metadata)
        for func in unit.get("functions") or []:
            match_percent = parse_float(func.get("fuzzy_match_percent"), 100.0)
            if match_percent >= 100 and not audit_fuzzy_100:
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


def default_checkdiff_runner(
    function: str,
    *,
    timeout: float | None = DEFAULT_CHECKDIFF_TIMEOUT,
) -> tuple[int, str, str]:
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
        timeout=timeout,
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


def _offset_displacement(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value.get(key)
    return None


def struct_offset_discrepancies(
    classification: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = classification.get("offset_discrepancies") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        base = str(item.get("base_reg") or item.get("base") or "").strip()
        if not base or base.lower() in NON_STRUCT_BASE_REGS:
            continue
        cur_disp = _offset_displacement(
            item,
            "cur_disp",
            "current_disp",
            "current_offset",
            "cur_offset",
        )
        ref_disp = _offset_displacement(
            item,
            "ref_disp",
            "expected_disp",
            "reference_disp",
            "ref_offset",
        )
        normalized = dict(item)
        normalized["base_reg"] = base
        normalized["cur_disp"] = cur_disp
        normalized["ref_disp"] = ref_disp
        out.append(normalized)
    return out


def offset_discrepancy_summary(
    classification: dict[str, Any],
) -> dict[str, Any]:
    discrepancies = struct_offset_discrepancies(classification)
    bases = list(
        dict.fromkeys(str(item.get("base_reg") or "") for item in discrepancies)
    )
    disp_parts: list[str] = []
    for item in discrepancies:
        cur_disp = item.get("cur_disp")
        ref_disp = item.get("ref_disp")
        if cur_disp is None and ref_disp is None:
            continue
        disp_parts.append(f"current:{cur_disp} expected:{ref_disp}")
    opcodes = list(
        dict.fromkeys(
            str(item.get("opcode") or "")
            for item in discrepancies
            if item.get("opcode")
        )
    )
    return {
        "offset_discrepancies": discrepancies,
        "offset_discrepancy_count": len(discrepancies),
        "offset_discrepancy_bases": ",".join(bases),
        "offset_discrepancy_disps": "; ".join(disp_parts),
        "offset_discrepancy_opcodes": ",".join(opcodes),
    }


