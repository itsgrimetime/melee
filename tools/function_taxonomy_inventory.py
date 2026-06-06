#!/usr/bin/env python3
"""Generate function mismatch taxonomy artifacts from report.json + checkdiff."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
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

from src.mwcc_debug.frame_taxonomy import classify_frame_taxonomy

DEFAULT_REPORT = REPO_ROOT / "build" / "GALE01" / "report.json"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "function-taxonomy"
DEFAULT_CHECKDIFF_TIMEOUT = 120.0
DEFAULT_DECL_ORDER_TIMEOUT = 180.0
DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT = 60.0
DEFAULT_PROGRESS_INTERVAL = 30.0
RUN_STATUS_FILENAME = "run-status.json"
RUN_STATUS_SCHEMA_VERSION = 1
_DECL_ORDER_EVAL_LOCK = threading.Lock()
NON_STRUCT_BASE_REGS = {"r1", "r2", "r13"}
DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS = {
    "no-name-magic-candidate": "blocked-data-symbol-no-name-magic-candidate",
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

    if primary == "bss-anchor-ceiling" or classification.get(
        "bss_anchor_relocations"
    ):
        return "data-symbol-relocation", "bss-section-anchor-ceiling", False
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
    if primary == "control-flow-source-shape":
        return "structural-reconstruction", "branch-or-control-flow-shape", False
    if primary == "instruction-sequence":
        return "structural-reconstruction", "opcode-sequence-diff", False
    if struct_offset_discrepancies(classification):
        return "struct-offset-discrepancy", "struct-field-offset-displacement", False
    if is_known_small_candidate(candidate, payload):
        return "known-small-pattern-candidate", "small-opcode-or-operand-pattern", True
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
            "source_actionability": "manual-small-pattern",
            "headline_tool": "mismatch-db",
            "actionability_reason": (
                "small operand/opcode pattern likely has a targeted source "
                "edit, but no source-emitting harvest harness is registered "
                "yet; use mismatch-db as an advisory manual workflow"
            ),
        }
    if bucket == "signature-call-type":
        return {
            "source_actionability": "advisory-signature-audit",
            "headline_tool": "debug-suggest-signatures",
            "actionability_reason": (
                "call shape or prototype mismatch; run signature audit to inspect "
                "call-prep, prototypes, argument widths, and concrete rebucket reasons"
            ),
        }
    if bucket == "inline-boundary":
        return {
            "source_actionability": "manual-inline-guidance",
            "headline_tool": "patterns-inlines",
            "actionability_reason": (
                "inline/call boundary mismatch; compare helper definitions and "
                "call-preserving source forms manually because patterns-inlines "
                "does not emit bounded source candidates"
            ),
        }
    if bucket == "data-symbol-relocation":
        if subcategory == "bss-section-anchor-ceiling":
            return {
                "source_actionability": "ceiling",
                "headline_tool": "checkdiff-name-magic",
                "actionability_reason": (
                    "named BSS versus .bss.0 section-anchor residual; current "
                    "tooling labels this as a compiler or linker anchor ceiling "
                    "unless a validated source candidate proves otherwise"
                ),
            }
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
    if bucket == "struct-offset-discrepancy":
        return {
            "source_actionability": "current-tools-struct-verify",
            "headline_tool": "struct-verify",
            "actionability_reason": (
                "base-register field displacement mismatch; run struct verify "
                "with the reported base register and offsets before treating "
                "this as allocator noise"
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


def next_command(
    bucket: str,
    subcategory: str,
    candidate: FunctionCandidate,
    classification: dict[str, Any] | None = None,
) -> str:
    function = candidate.function
    source_path = f"src/{candidate.file_path}"
    if bucket == "signature-call-type":
        if candidate.file_path:
            return (
                f"melee-agent debug suggest signatures -f {function} "
                f"--source-file {source_path} --json"
            )
        return f"melee-agent debug suggest signatures -f {function} --json"
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
    if bucket == "struct-offset-discrepancy":
        summary = offset_discrepancy_summary(classification or {})
        bases = [
            base
            for base in str(summary.get("offset_discrepancy_bases") or "").split(",")
            if base
        ]
        base_arg = f" --base {bases[0]}" if len(bases) == 1 else " --base <base-reg>"
        return (
            f"melee-agent struct verify {function} --struct <struct-name>"
            f"{base_arg} --tu-src {source_path} --json"
        )
    if bucket == "register-allocator":
        return (
            "melee-agent debug dump setup && "
            f"melee-agent debug dump local {source_path} --function {function}"
        )
    return f"python tools/checkdiff.py {function} --compact"


def _name_magic_preflight_command(candidate: FunctionCandidate) -> list[str]:
    return [
        "melee-agent",
        "debug",
        "mutate",
        "name-magic-source-declarations",
        "-f",
        candidate.function,
        "--source-file",
        f"src/{candidate.file_path}",
        "--no-compile-probes",
        "--no-score-match-percent",
        "--json",
    ]


def default_name_magic_preflight_runner(
    candidate: FunctionCandidate,
    *,
    timeout: float | None = DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT,
) -> dict[str, Any] | None:
    source_path = REPO_ROOT / "src" / candidate.file_path
    if not source_path.exists():
        return None
    try:
        proc = subprocess.run(
            _name_magic_preflight_command(candidate),
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return parse_json_object(proc.stdout)
    except Exception:
        return None


def _payload_probe_count(payload: dict[str, Any]) -> int:
    raw_count = payload.get("probe_count")
    if raw_count is not None:
        return parse_int(raw_count)
    probes = payload.get("probes")
    if isinstance(probes, list):
        return len(probes)
    variants = payload.get("variants")
    if isinstance(variants, list):
        return len(variants)
    return 0


def attach_name_magic_preflight(
    record: dict[str, Any],
    candidate: FunctionCandidate,
    payload: dict[str, Any] | None,
) -> None:
    if payload is None:
        return
    stop_condition = payload.get("stop_condition")
    if not isinstance(stop_condition, dict):
        stop_condition = {}
    blocker = str(
        payload.get("blocker") or stop_condition.get("blocker") or ""
    ).strip()
    stop_kind = str(stop_condition.get("kind") or "").strip()
    reason = str(
        stop_condition.get("reason") or payload.get("reason") or blocker
    ).strip()
    probe_count = _payload_probe_count(payload)

    record["name_magic_blocker"] = blocker
    record["name_magic_stop_kind"] = stop_kind
    record["name_magic_probe_count"] = probe_count
    record["name_magic_reason"] = reason

    if not blocker or probe_count > 0:
        return
    source_actionability = DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS.get(blocker)
    if source_actionability is None:
        return

    detail = reason or blocker
    record["source_actionability"] = source_actionability
    record["headline_tool"] = "checkdiff-name-magic"
    record["actionability_reason"] = (
        f"{blocker}; {detail}; no source-emitting name-magic candidate was "
        "produced by current tooling"
    )
    record["next_command"] = " ".join(_name_magic_preflight_command(candidate))


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
    record["frame_match_relevance"] = frame_taxonomy.get("match_relevance")
    record["frame_match_relevance_reason"] = frame_taxonomy.get(
        "match_relevance_reason"
    )
    if frame_taxonomy.get("next_command"):
        record["next_command"] = frame_taxonomy["next_command"]


def default_decl_order_evaluator(
    candidate: FunctionCandidate,
    _record: dict[str, Any],
    *,
    timeout: float | None = DEFAULT_DECL_ORDER_TIMEOUT,
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
    try:
        with _DECL_ORDER_EVAL_LOCK:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        return {
            "evaluated_status": "unevaluated: decl-orders timed out",
            "candidate_count": 0,
            "best_decl_delta": None,
            "best_ordering": "",
            "stdout_tail": _tail_text(exc.output),
            "stderr_tail": _tail_text(exc.stderr)
            or f"decl-orders timed out after {_format_timeout(exc.timeout)}",
        }
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
    name_magic_preflight_runner: NameMagicPreflightRunner | None = (
        default_name_magic_preflight_runner
    ),
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    started = time.perf_counter()
    try:
        returncode, stdout, stderr = runner(candidate.function)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - started
        stdout_tail = _tail_text(exc.output)
        stderr_tail = _tail_text(exc.stderr)
        return None, {
            "function": candidate.function,
            "error": "checkdiff_timeout",
            "file_path": candidate.file_path,
            "message": f"checkdiff timed out after {_format_timeout(exc.timeout)}",
            "returncode": 124,
            "elapsed_sec": round(elapsed, 3),
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }
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
    if payload.get("match") is True or primary == "instruction-identical":
        return None, None
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
    if bucket == "data-symbol-relocation" and name_magic_preflight_runner is not None:
        try:
            name_magic_payload = name_magic_preflight_runner(candidate)
        except Exception:
            name_magic_payload = None
        attach_name_magic_preflight(record, candidate, name_magic_payload)
    offset_summary = offset_discrepancy_summary(classification)
    if offset_summary["offset_discrepancy_count"]:
        record.update(offset_summary)
        record["next_command"] = next_command(
            bucket,
            subcategory,
            candidate,
            classification,
        )
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
        "offset_discrepancy_count",
        "offset_discrepancy_bases",
        "offset_discrepancy_disps",
        "offset_discrepancy_opcodes",
        "frame_cause",
        "frame_verdict",
        "frame_closability_tier",
        "frame_match_relevance",
        "frame_match_relevance_reason",
        "frame_attribution_status",
        "frame_source_object_symbol",
        "cast_audit_status",
        "cast_medium_plus_count",
        "source_actionability",
        "headline_tool",
        "actionability_reason",
        "name_magic_blocker",
        "name_magic_stop_kind",
        "name_magic_probe_count",
        "name_magic_reason",
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
        "offset_discrepancy_count",
        "offset_discrepancy_bases",
        "offset_discrepancy_disps",
        "offset_discrepancy_opcodes",
        "frame_cause",
        "frame_verdict",
        "frame_closability_tier",
        "frame_match_relevance",
        "frame_match_relevance_reason",
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
        "name_magic_blocker",
        "name_magic_stop_kind",
        "name_magic_probe_count",
        "name_magic_reason",
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


def write_data_symbol_blocker_subqueues(
    queues: Path,
    records: list[dict[str, Any]],
) -> None:
    for blocker, source_actionability in DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS.items():
        rows = [
            row
            for row in records
            if row.get("work_bucket") == "data-symbol-relocation"
            and row.get("source_actionability") == source_actionability
            and row.get("name_magic_blocker") == blocker
        ]
        write_queue(queues / f"data-symbol-relocation.{blocker}.tsv", rows)


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
        f"| Report audit candidates | {report_non100_count} |",
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
    for blocker in DATA_SYMBOL_NAME_MAGIC_REBUCKET_BLOCKERS:
        lines.append(
            "- "
            f"`build/function-taxonomy/queues/data-symbol-relocation.{blocker}.tsv`"
        )
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


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _base_run_status(
    *,
    report_path: Path,
    output_dir: Path,
    candidates: list[FunctionCandidate],
    attempted: list[FunctionCandidate],
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_STATUS_SCHEMA_VERSION,
        "status": "running",
        "started_at": started_at,
        "report_path": str(report_path),
        "output_dir": str(output_dir),
        "report_non100_count": len(candidates),
        "attempted_count": len(attempted),
    }


def _initial_run_status(
    *,
    report_path: Path,
    output_dir: Path,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_STATUS_SCHEMA_VERSION,
        "status": "running",
        "started_at": started_at,
        "report_path": str(report_path),
        "output_dir": str(output_dir),
        "report_non100_count": 0,
        "attempted_count": 0,
    }


def write_run_status(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(output_dir / RUN_STATUS_FILENAME, payload)


def _mark_run_failed(
    output_dir: Path,
    run_status: dict[str, Any],
    exc: BaseException,
    *,
    records: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> None:
    failed_status = dict(run_status)
    failed_status.update(
        {
            "status": "failed",
            "failed_at": _utc_now_iso(),
            "error": str(exc) or exc.__class__.__name__,
            "error_type": exc.__class__.__name__,
            "classified_count": len(records or []),
            "error_count": len(errors or []),
        }
    )
    write_run_status(output_dir, failed_status)


def generate_inventory(
    report_path: Path | str = DEFAULT_REPORT,
    output_dir: Path | str = DEFAULT_OUTPUT,
    *,
    checkdiff_runner: CheckdiffRunner = default_checkdiff_runner,
    decl_order_evaluator: DeclOrderEvaluator | None = default_decl_order_evaluator,
    frame_report_runner: FrameReportRunner | None = default_frame_report_runner,
    cast_audit_runner: CastAuditRunner | None = default_cast_audit_runner,
    name_magic_preflight_runner: NameMagicPreflightRunner | None = (
        default_name_magic_preflight_runner
    ),
    workers: int = 4,
    limit: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_interval: float | None = DEFAULT_PROGRESS_INTERVAL,
) -> InventoryResult:
    report_path = Path(report_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "queues").mkdir(exist_ok=True)
    started_at = _utc_now_iso()
    run_status = _initial_run_status(
        report_path=report_path,
        output_dir=output_dir,
        started_at=started_at,
    )
    write_run_status(output_dir, run_status)
    try:
        candidates = load_report_candidates(report_path)
    except BaseException as exc:
        _mark_run_failed(output_dir, run_status, exc)
        raise
    attempted = candidates[:limit] if limit is not None else candidates

    run_status = _base_run_status(
        report_path=report_path,
        output_dir=output_dir,
        candidates=candidates,
        attempted=attempted,
        started_at=started_at,
    )
    write_run_status(output_dir, run_status)

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        max_workers = max(1, workers)
        pending: dict[
            Future[tuple[dict[str, Any] | None, dict[str, Any] | None]],
            FunctionCandidate,
        ] = {}
        candidate_iter = iter(attempted)
        last_progress_at = 0.0

        def emit_progress(event: dict[str, Any]) -> None:
            if progress_callback is not None:
                progress_callback(event)

        def emit_periodic_progress() -> None:
            completed_count = len(records) + len(errors)
            active_functions = [candidate.function for candidate in pending.values()]
            event = {
                "event": "inventory_progress",
                "attempted_count": len(attempted),
                "submitted_count": completed_count + len(pending),
                "completed_count": completed_count,
                "classified_count": len(records),
                "error_count": len(errors),
                "pending_count": len(pending),
                "remaining_count": max(
                    0,
                    len(attempted) - completed_count - len(pending),
                ),
                "active_functions": active_functions,
            }
            progress_status = dict(run_status)
            progress_status.update(
                {
                    "status": "running",
                    "updated_at": _utc_now_iso(),
                    "submitted_count": event["submitted_count"],
                    "completed_count": completed_count,
                    "classified_count": len(records),
                    "error_count": len(errors),
                    "pending_count": len(pending),
                    "active_functions": active_functions,
                }
            )
            write_run_status(output_dir, progress_status)
            emit_progress(event)

        def emit_progress_if_due() -> None:
            nonlocal last_progress_at
            if progress_interval is None or progress_interval <= 0:
                return
            now = time.monotonic()
            if now - last_progress_at < progress_interval:
                return
            emit_periodic_progress()
            last_progress_at = now

        def submit_next(executor: ThreadPoolExecutor) -> None:
            try:
                candidate = next(candidate_iter)
            except StopIteration:
                return
            future = executor.submit(
                classify_candidate,
                candidate,
                checkdiff_runner,
                decl_order_evaluator,
                frame_report_runner,
                cast_audit_runner,
                name_magic_preflight_runner,
            )
            pending[future] = candidate
            emit_progress({"event": "candidate_submitted", "function": candidate.function})

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for _ in range(min(max_workers, len(attempted))):
                submit_next(executor)
            while pending:
                wait_timeout = (
                    None
                    if progress_interval is None or progress_interval <= 0
                    else progress_interval
                )
                done, _not_done = wait(
                    pending,
                    timeout=wait_timeout,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    emit_periodic_progress()
                    last_progress_at = time.monotonic()
                    continue
                for future in done:
                    candidate = pending.pop(future)
                    try:
                        record, error = future.result()
                    except BaseException as exc:
                        _mark_run_failed(
                            output_dir,
                            run_status,
                            exc,
                            records=records,
                            errors=errors,
                        )
                        for remaining in pending:
                            remaining.cancel()
                        raise
                    if record is not None:
                        records.append(record)
                    if error is not None:
                        errors.append(error)
                    emit_progress(
                        {
                            "event": "candidate_done",
                            "function": candidate.function,
                            "classified_count": len(records),
                            "error_count": len(errors),
                        }
                    )
                    submit_next(executor)
                emit_progress_if_due()

        records.sort(key=lambda row: (-parse_float(row.get("match_percent")), row.get("function", "")))
        errors.sort(key=lambda row: row.get("function", ""))

        queues = output_dir / "queues"

        write_jsonl(output_dir / "taxonomy.records.jsonl", records)
        write_csv(output_dir / "taxonomy.records.csv", records)
        write_jsonl(output_dir / "checkdiff-errors.jsonl", errors)
        write_placeholder_auxiliary_files(output_dir)

        for bucket in BUCKET_ORDER:
            bucket_rows = [row for row in records if row.get("work_bucket") == bucket]
            write_queue(queues / f"{bucket}.tsv", bucket_rows)
        write_data_symbol_blocker_subqueues(queues, records)
        write_error_queue(queues / "checkdiff-errors.tsv", errors)
        write_summary(
            output_dir / "summary.md",
            report_non100_count=len(candidates),
            records=records,
            errors=errors,
        )
        completed_status = dict(run_status)
        completed_status.update(
            {
                "status": "completed",
                "completed_at": _utc_now_iso(),
                "classified_count": len(records),
                "error_count": len(errors),
            }
        )
        write_run_status(output_dir, completed_status)
    except BaseException as exc:
        current_status = {}
        status_path = output_dir / RUN_STATUS_FILENAME
        try:
            current_status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        if current_status.get("status") != "failed":
            _mark_run_failed(
                output_dir,
                run_status,
                exc,
                records=records,
                errors=errors,
            )
        raise

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
        help="Only process the first N report mismatch/audit candidate functions.",
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
    parser.add_argument(
        "--skip-name-magic-preflight",
        action="store_true",
        help=(
            "Skip no-compile name-magic preflight for data-symbol rows. "
            "This is faster, but leaves stable non-candidate blockers in the "
            "current-tools-data-symbol queue."
        ),
    )
    parser.add_argument(
        "--checkdiff-timeout",
        type=float,
        default=DEFAULT_CHECKDIFF_TIMEOUT,
        help=(
            "Per-function checkdiff timeout in seconds "
            f"(default: {DEFAULT_CHECKDIFF_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--decl-order-timeout",
        type=float,
        default=DEFAULT_DECL_ORDER_TIMEOUT,
        help=(
            "Per-function decl-orders evaluation timeout in seconds "
            f"(default: {DEFAULT_DECL_ORDER_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--name-magic-preflight-timeout",
        type=float,
        default=DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT,
        help=(
            "Per-function name-magic preflight timeout in seconds "
            f"(default: {DEFAULT_NAME_MAGIC_PREFLIGHT_TIMEOUT:g}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=(
            "Print and persist running progress every N seconds while all "
            f"workers are busy (default: {DEFAULT_PROGRESS_INTERVAL:g}; "
            "0 disables periodic progress)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    checkdiff_timeout = None if args.checkdiff_timeout <= 0 else args.checkdiff_timeout
    decl_order_timeout = None if args.decl_order_timeout <= 0 else args.decl_order_timeout
    name_magic_preflight_timeout = (
        None
        if args.name_magic_preflight_timeout <= 0
        else args.name_magic_preflight_timeout
    )
    progress_interval = None if args.progress_interval <= 0 else args.progress_interval
    output_dir = Path(args.output).resolve()

    def mark_interrupted(signum: int, _frame: Any) -> None:
        status_path = output_dir / RUN_STATUS_FILENAME
        current_status: dict[str, Any] = {}
        try:
            current_status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        interrupted_status = dict(current_status)
        interrupted_status.update(
            {
                "schema_version": RUN_STATUS_SCHEMA_VERSION,
                "status": "failed",
                "failed_at": _utc_now_iso(),
                "error": f"interrupted by signal {signum}",
                "error_type": "SignalInterrupt",
            }
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        write_run_status(output_dir, interrupted_status)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, mark_interrupted)

    def progress(event: dict[str, Any]) -> None:
        if event.get("event") != "inventory_progress":
            return
        active = ", ".join(str(fn) for fn in event.get("active_functions") or [])
        active_suffix = f"; active: {active}" if active else ""
        print(
            "[taxonomy] "
            f"{event.get('completed_count', 0)}/{event.get('attempted_count', 0)} "
            f"done, {event.get('pending_count', 0)} running, "
            f"{event.get('classified_count', 0)} classified, "
            f"{event.get('error_count', 0)} errors"
            f"{active_suffix}",
            file=sys.stderr,
            flush=True,
        )

    try:
        result = generate_inventory(
            args.report,
            args.output,
            checkdiff_runner=lambda function: default_checkdiff_runner(
                function,
                timeout=checkdiff_timeout,
            ),
            workers=args.workers,
            limit=args.limit,
            decl_order_evaluator=(
                None
                if args.skip_decl_order_eval
                else lambda candidate, record: default_decl_order_evaluator(
                    candidate,
                    record,
                    timeout=decl_order_timeout,
                )
            ),
            frame_report_runner=(
                None
                if args.skip_frame_report_attribution
                else default_frame_report_runner
            ),
            name_magic_preflight_runner=(
                None
                if args.skip_name_magic_preflight
                else lambda candidate: default_name_magic_preflight_runner(
                    candidate,
                    timeout=name_magic_preflight_timeout,
                )
            ),
            progress_callback=progress,
            progress_interval=progress_interval,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    print(f"Generated taxonomy artifacts in {result.output_dir}")
    print(
        "Rows: "
        f"{result.report_non100_count} report audit candidates, "
        f"{result.attempted_count} attempted, "
        f"{result.classified_count} classified, "
        f"{result.error_count} errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
