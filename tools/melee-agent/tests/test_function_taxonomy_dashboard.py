from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_minimal_taxonomy_dir(path: Path) -> None:
    path.mkdir()
    write_jsonl(
        path / "taxonomy.records.jsonl",
        [
            {
                "function": "ftDemo_80000000",
                "match_percent": 99.5,
                "work_bucket": "signature-call-type",
                "primary": "signature-type-mismatch",
            }
        ],
    )
    write_jsonl(path / "checkdiff-errors.jsonl", [{"function": "bad"}])
    write_jsonl(path / "report-only-nonextract-backed.jsonl", [{"function": "report"}])
    write_jsonl(path / "db-completed-extract-backed-non100.jsonl", [{"function": "done"}])
    queues = path / "queues"
    queues.mkdir()
    (queues / "signature-call-type.tsv").write_text(
        "match_percent\tfunction\n99.5\tftDemo_80000000\n98.0\tftOther\n",
        encoding="utf-8",
    )


def read_dashboard_payload(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = "window.__TAXONOMY_DASHBOARD_DATA__ = "
    assert text.startswith(prefix)
    assert text.endswith(";\n")
    return json.loads(text[len(prefix) : -2])


def test_generate_dashboard_copies_template_and_embeds_taxonomy_data(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    write_minimal_taxonomy_dir(taxonomy_dir)
    template = tmp_path / "template.html"
    template.write_text(
        "<!doctype html><script src=\"dashboard-data.js\"></script>",
        encoding="utf-8",
    )

    result = generate_dashboard(taxonomy_dir, template_path=template)

    assert result.dashboard_html == taxonomy_dir / "dashboard.html"
    assert result.dashboard_data_js == taxonomy_dir / "dashboard-data.js"
    assert result.record_count == 1
    assert result.queue_count == 1
    assert result.dashboard_html.read_text(encoding="utf-8") == template.read_text(
        encoding="utf-8"
    )

    payload = read_dashboard_payload(result.dashboard_data_js)
    assert payload["records"][0]["function"] == "ftDemo_80000000"
    assert payload["errors"] == [{"function": "bad"}]
    assert payload["reportOnly"] == [{"function": "report"}]
    assert payload["dbCompleted"] == [{"function": "done"}]
    assert payload["queueCounts"] == {"signature-call-type.tsv": 2}


def test_generate_dashboard_reports_missing_required_inputs(tmp_path: Path) -> None:
    from tools.function_taxonomy_dashboard import generate_dashboard

    taxonomy_dir = tmp_path / "taxonomy"
    taxonomy_dir.mkdir()
    template = tmp_path / "template.html"
    template.write_text("<!doctype html>", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="taxonomy.records.jsonl"):
        generate_dashboard(taxonomy_dir, template_path=template)


def test_default_dashboard_template_loads_embedded_data() -> None:
    from tools.function_taxonomy_dashboard import DEFAULT_TEMPLATE_PATH

    text = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "dashboard-data.js" in text
    assert "window.__TAXONOMY_DASHBOARD_DATA__" in text
    assert "Taxonomy guide" in text
    assert "closabilityFilter" in text
    assert "frame_closability_tier" in text
    assert "frame_source_object_symbol" in text
    assert "Frame closability" in text
    assert 'for (const id of ["search", "bucketFilter", "tierFilter", "primaryFilter", "closabilityFilter", "minMatch"])' in text
    assert 'if (closability && row.frame_closability_tier !== closability) return false;' in text
