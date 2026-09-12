#!/usr/bin/env python3
"""Generate the function taxonomy dashboard from taxonomy inventory artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.function_taxonomy_schema import (
    SCHEMA_VERSION,
    build_dashboard_manifest,
    normalize_frame_record,
    normalize_root_cause_record,
    normalize_routing_record,
    normalize_semantic_delta_record,
)

DEFAULT_TAXONOMY_DIR = REPO_ROOT / "build" / "function-taxonomy"
DEFAULT_TEMPLATE_PATH = Path(__file__).with_name(
    "function_taxonomy_dashboard_template.html"
)
DEFAULT_MODEL_PATH = Path(__file__).with_name("function_taxonomy_dashboard_model.js")

JSONL_INPUTS = {
    "records": "taxonomy.records.jsonl",
    "errors": "checkdiff-errors.jsonl",
    "reportOnly": "report-only-nonextract-backed.jsonl",
    "dbCompleted": "db-completed-extract-backed-non100.jsonl",
}

SCALAR_DIMENSIONS = (
    ("work_bucket", "bucketOrder", "bucketInfo"),
    ("match_tier", "tierOrder", None),
    ("primary", "primaryOrder", "primaryInfo"),
    ("source_actionability", "actionabilityOrder", "actionabilityInfo"),
    ("frame_evidence", "frameEvidenceOrder", "frameEvidenceInfo"),
    ("frame_probe_status", "frameProbeStatusOrder", "frameProbeStatusInfo"),
    ("frame_match_relevance", "frameMatchRelevanceOrder", "frameMatchRelevanceInfo"),
    ("primary_intervention", "interventionOrder", "interventionInfo"),
    ("evidence_stage", "evidenceStageOrder", "evidenceStageInfo"),
    ("opcode_edit_direction", "opcodeEditDirectionOrder", "opcodeEditDirectionInfo"),
    (
        "normalized_trigger_family",
        "normalizedTriggerFamilyOrder",
        "normalizedTriggerFamilyInfo",
    ),
)
MULTI_VALUE_DIMENSIONS = (
    ("secondary_signals", "secondarySignalOrder", "secondarySignalInfo"),
    ("blocker_families", "blockerFamilyOrder", "blockerFamilyInfo"),
    (
        "semantic_delta_families",
        "semanticDeltaFamilyOrder",
        "semanticDeltaFamilyInfo",
    ),
    ("root_cause_keys", "rootCauseKeyOrder", "rootCauseKeyInfo"),
)


@dataclass(frozen=True)
class DashboardGenerationResult:
    dashboard_html: Path
    dashboard_data_js: Path
    dashboard_model_js: Path
    record_count: int
    error_count: int
    report_only_count: int
    db_completed_count: int
    queue_count: int
    node_checked: bool


class InlineScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inline_scripts: list[str] = []
        self.external_scripts: list[str] = []
        self._in_script = False
        self._script_chunks: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "script":
            return
        attr_map = dict(attrs)
        src = attr_map.get("src")
        if src:
            self.external_scripts.append(src)
        self._in_script = True
        self._script_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._in_script:
            return
        script = "".join(self._script_chunks).strip()
        if script:
            self.inline_scripts.append(script)
        self._in_script = False


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Required taxonomy input is missing: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSONL row") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object row")
        rows.append(row)
    return rows


def count_tsv_rows(path: Path) -> int:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    return max(0, len(lines) - 1)


def read_queue_counts(queue_dir: Path) -> dict[str, int]:
    if not queue_dir.exists():
        return {}
    return {
        path.name: count_tsv_rows(path)
        for path in sorted(queue_dir.glob("*.tsv"))
        if path.is_file()
    }


def build_dashboard_payload(taxonomy_dir: Path) -> dict[str, Any]:
    taxonomy_dir = taxonomy_dir.resolve()
    payload = {
        key: read_jsonl(taxonomy_dir / filename)
        for key, filename in JSONL_INPUTS.items()
    }
    payload["records"] = [
        normalize_root_cause_record(
            normalize_semantic_delta_record(
                normalize_routing_record(normalize_frame_record(row))
            )
        )
        for row in payload["records"]
        if float(row.get("match_percent", 100.0)) < 100.0
    ]
    queue_counts = read_queue_counts(taxonomy_dir / "queues")
    payload["queueCounts"] = queue_counts
    payload["taxonomyManifest"] = build_dashboard_manifest(
        payload["records"], queue_counts
    )
    validate_dashboard_payload(payload)
    return payload


def validate_dashboard_payload(payload: dict[str, Any]) -> None:
    manifest = payload.get("taxonomyManifest")
    if not isinstance(manifest, dict):
        raise ValueError("taxonomy manifest is missing")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(
            f"taxonomy manifest schemaVersion must be {SCHEMA_VERSION}"
        )

    records = payload.get("records", [])
    for record_key, order_key, info_key in SCALAR_DIMENSIONS:
        observed = {str(row[record_key]) for row in records if row.get(record_key)}
        order = manifest.get(order_key, [])
        omitted_order = sorted(observed.difference(order))
        if omitted_order:
            raise ValueError(
                f"taxonomy manifest {record_key} order omits: "
                f"{', '.join(omitted_order)}"
            )
        if info_key is not None:
            info = manifest.get(info_key, {})
            omitted_info = sorted(observed.difference(info))
            if omitted_info:
                raise ValueError(
                    f"taxonomy manifest {record_key} info omits: "
                    f"{', '.join(omitted_info)}"
                )

    for record_key, order_key, info_key in MULTI_VALUE_DIMENSIONS:
        observed = {
            value.strip()
            for row in records
            for value in (
                row.get(record_key)
                if isinstance(row.get(record_key), (list, tuple))
                else []
            )
            if isinstance(value, str) and value.strip()
        }
        order = manifest.get(order_key, [])
        omitted_order = sorted(observed.difference(order))
        if omitted_order:
            raise ValueError(
                f"taxonomy manifest {record_key} order omits: "
                f"{', '.join(omitted_order)}"
            )
        info = manifest.get(info_key, {})
        omitted_info = sorted(observed.difference(info))
        if omitted_info:
            raise ValueError(
                f"taxonomy manifest {record_key} info omits: "
                f"{', '.join(omitted_info)}"
            )

    queue_counts = payload.get("queueCounts", {})
    queue_files = manifest.get("queueFiles", [])
    if set(queue_counts) != set(queue_files):
        difference = sorted(set(queue_counts).symmetric_difference(queue_files))
        raise ValueError(f"taxonomy manifest queues differ: {', '.join(difference)}")


def write_dashboard_data(path: Path, payload: dict[str, Any]) -> None:
    text = "window.__TAXONOMY_DASHBOARD_DATA__ = "
    text += json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text += ";\n"
    path.write_text(text, encoding="utf-8")


def parse_dashboard_html(path: Path) -> InlineScriptParser:
    parser = InlineScriptParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def node_check(path: Path) -> None:
    subprocess.run(["node", "--check", str(path)], check=True)


def validate_dashboard_files(
    dashboard_html: Path,
    dashboard_data_js: Path,
    dashboard_model_js: Path,
    *,
    node_checks: bool,
) -> bool:
    parser = parse_dashboard_html(dashboard_html)
    if "dashboard-data.js" not in parser.external_scripts:
        raise ValueError(f"{dashboard_html} must load dashboard-data.js")
    if "dashboard-model.js" not in parser.external_scripts:
        raise ValueError(f"{dashboard_html} must load dashboard-model.js")

    if not node_checks or shutil.which("node") is None:
        return False

    node_check(dashboard_data_js)
    node_check(dashboard_model_js)
    if parser.inline_scripts:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".js",
            prefix="dashboard-inline-check-",
            delete=False,
        ) as tmp:
            inline_check = Path(tmp.name)
            tmp.write("\n;\n".join(parser.inline_scripts))
        try:
            node_check(inline_check)
        finally:
            inline_check.unlink(missing_ok=True)
    return True


def generate_dashboard(
    taxonomy_dir: Path | str = DEFAULT_TAXONOMY_DIR,
    *,
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
    node_checks: bool = True,
) -> DashboardGenerationResult:
    taxonomy_dir = Path(taxonomy_dir).resolve()
    template_path = Path(template_path).resolve()
    if not taxonomy_dir.exists():
        raise FileNotFoundError(f"Taxonomy directory does not exist: {taxonomy_dir}")
    if not template_path.exists():
        raise FileNotFoundError(f"Dashboard template does not exist: {template_path}")

    payload = build_dashboard_payload(taxonomy_dir)
    dashboard_html = taxonomy_dir / "dashboard.html"
    dashboard_data_js = taxonomy_dir / "dashboard-data.js"
    dashboard_model_js = taxonomy_dir / "dashboard-model.js"

    dashboard_html.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    write_dashboard_data(dashboard_data_js, payload)
    dashboard_model_js.write_text(DEFAULT_MODEL_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    node_checked = validate_dashboard_files(
        dashboard_html,
        dashboard_data_js,
        dashboard_model_js,
        node_checks=node_checks,
    )

    return DashboardGenerationResult(
        dashboard_html=dashboard_html,
        dashboard_data_js=dashboard_data_js,
        dashboard_model_js=dashboard_model_js,
        record_count=len(payload["records"]),
        error_count=len(payload["errors"]),
        report_only_count=len(payload["reportOnly"]),
        db_completed_count=len(payload["dbCompleted"]),
        queue_count=len(payload["queueCounts"]),
        node_checked=node_checked,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate build/function-taxonomy/dashboard.html and dashboard-data.js."
    )
    parser.add_argument(
        "taxonomy_dir",
        nargs="?",
        default=DEFAULT_TAXONOMY_DIR,
        type=Path,
        help="Directory containing taxonomy.records.jsonl, auxiliary JSONL files, and queues/.",
    )
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE_PATH,
        type=Path,
        help="Dashboard HTML template to copy into the taxonomy directory.",
    )
    parser.add_argument(
        "--skip-node-check",
        action="store_true",
        help="Skip node --check syntax validation for generated JavaScript.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = generate_dashboard(
            args.taxonomy_dir,
            template_path=args.template,
            node_checks=not args.skip_node_check,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Generated {result.dashboard_html}")
    print(f"Generated {result.dashboard_data_js}")
    print(f"Generated {result.dashboard_model_js}")
    print(
        "Rows: "
        f"{result.record_count} unmatched functions, "
        f"{result.error_count} checkdiff errors, "
        f"{result.report_only_count} report-only, "
        f"{result.db_completed_count} DB-completed, "
        f"{result.queue_count} queue files"
    )
    print(f"Node syntax check: {'ran' if result.node_checked else 'skipped'}")
    print(f"Open: {result.dashboard_html.as_uri()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
