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
import time
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / "build" / "GALE01" / "report.json"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "function-taxonomy"

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


def classify_bucket(
    candidate: FunctionCandidate, payload: dict[str, Any]
) -> tuple[str, str, bool]:
    classification = payload.get("classification") or {}
    primary = classification.get("primary") or "unknown"
    reasons = classification.get("reasons") or []
    reason_text = "\n".join(str(reason).lower() for reason in reasons)

    if primary == "signature-type-mismatch":
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
        if "frame reservation gap" in reason_text or "pad_stack" in reason_text:
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


def next_command(bucket: str, candidate: FunctionCandidate) -> str:
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
        return (
            f"melee-agent extract get {function} && "
            f"python tools/checkdiff.py {function} --compact"
        )
    if bucket == "data-symbol-relocation":
        return f"python tools/checkdiff.py {function} --compact --no-name-magic"
    if bucket == "stack-local-layout":
        return f"python tools/checkdiff.py {function} --compact --pcdump <pcdump-if-available>"
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


def classify_candidate(
    candidate: FunctionCandidate, runner: CheckdiffRunner
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
    bucket, subcategory, known_small = classify_bucket(candidate, payload)
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
        "confidence": "heuristic",
        "elapsed_sec": round(elapsed, 3),
        "stderr_tail": stderr[-1000:],
        "next_command": next_command(bucket, candidate),
    }
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
        "file_path",
        "size_bytes",
        "next_command",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_queue(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["match_percent", "function", "primary", "subcategory", "file_path", "next_command"]
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
            lambda candidate: classify_candidate(candidate, checkdiff_runner),
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
