from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "taxonomy-pages.yml"


def run_taxonomy_validator(
    tmp_path: Path, row: dict[str, object] | list[dict[str, object]]
) -> subprocess.CompletedProcess[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "python3 - <<'PY'\n"
    start = text.index(marker) + len(marker)
    end = text.index("\n          PY", start)
    validator = textwrap.dedent(text[start:end])
    taxonomy_dir = tmp_path / "taxonomy"
    taxonomy_dir.mkdir(parents=True)
    rows = row if isinstance(row, list) else [row]
    (taxonomy_dir / "taxonomy.records.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8"
    )
    (taxonomy_dir / "checkdiff-errors.jsonl").write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment["TAXONOMY_DIR"] = str(taxonomy_dir)
    return subprocess.run(
        ["python", "-c", validator],
        text=True,
        capture_output=True,
        env=environment,
    )


def test_taxonomy_pages_workflow_is_fork_only_and_deploys_pages_artifact() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.repository == 'itsgrimetime/melee'" in text
    assert "pages: write" in text
    assert "id-token: write" in text
    assert "actions/configure-pages@" in text
    assert "actions/upload-pages-artifact@" in text
    assert "actions/deploy-pages@" in text
    assert "rm -rf orig" in text
    assert "ln -s /orig orig" in text


def test_taxonomy_pages_workflow_generates_inventory_then_dashboard() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    inventory = "python3 tools/function_taxonomy_inventory.py"
    validation = "Validate taxonomy artifacts"
    dashboard = "python3 tools/function_taxonomy_dashboard.py"
    assert inventory in text
    assert validation in text
    assert dashboard in text
    assert text.index(inventory) < text.index(dashboard)
    assert text.index(validation) < text.index(dashboard)
    assert "if errors > 0:" in text
    assert "refusing to publish" in text
    assert "records == 0 and errors > 0" not in text
    assert "--skip-decl-order-eval" in text
    assert "build/function-taxonomy" in text
    assert "_site/taxonomy" in text


def test_taxonomy_pages_workflow_validates_routing_facets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert '"primary_intervention"' in text
    assert '"secondary_signals"' in text
    assert '"evidence_stage"' in text
    assert '"blocker_families"' in text
    assert "isinstance(record[field], list)" in text


def test_taxonomy_pages_workflow_validates_route_local_semantic_delta_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    for field in (
        "semantic_delta_families",
        "opcode_edit_direction",
        "normalized_trigger_signature_status",
        "normalized_trigger_signature",
        "normalized_trigger_family",
        "normalized_trigger_cluster_size",
    ):
        assert f'"{field}"' in text
    assert 'subcategory == "opcode-sequence-diff"' in text
    assert 'bucket == "normalized-structural-near-match"' in text
    assert 'direction == "operand-shape-only"' in text
    assert 'opcode_status != "no-opcode-delta"' in text
    assert 'opcode_status != "available"' in text
    assert 'trigger_status != "available"' in text
    assert 'json.loads(record["normalized_trigger_signature"])' in text
    assert 'signature.get("version") != 1' in text
    assert 'signature.get("normalized_diff_lines") != normalized_diff_lines' in text
    assert 'signature.get("edit_direction") != direction' in text
    assert 'not isinstance(record.get("normalized_trigger_cluster_size"), int)' in text


def test_taxonomy_pages_workflow_validates_bss_root_cause_clusters() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert '"root_cause_keys"' in text
    assert '"max_root_cause_impact"' in text
    assert 'value.startswith("bss-symbol:")' in text
    assert "expected_root_cause_keys" in text
    assert "root cause keys disagree with structured BSS evidence" in text
    assert "root_cause_counts = Counter()" in text
    assert "root cause impact disagrees with aggregate membership" in text


def test_taxonomy_pages_validator_accepts_zero_line_near_residual_without_trigger(
    tmp_path: Path,
) -> None:
    row = {
        "function": "zero_line_near",
        "work_bucket": "normalized-structural-near-match",
        "subcategory": "unattributed-zero-normalized-structural-residual",
        "primary_intervention": "normalized-residual-attribution",
        "secondary_signals": ["normalized-structural-match"],
        "evidence_stage": "observed",
        "blocker_families": ["residual-attribution"],
        "classification": {
            "structural_truth_gate": {
                "status": "structural-match",
                "normalized_diff_lines": 0,
            }
        },
        "opcode_delta_signature_status": "no-opcode-delta",
        "opcode_delta_signature": "",
        "semantic_delta_families": [],
        "opcode_edit_direction": "",
    }
    result = run_taxonomy_validator(tmp_path, row)

    assert result.returncode == 0, result.stderr


def test_taxonomy_pages_validator_still_rejects_one_line_near_without_trigger(
    tmp_path: Path,
) -> None:
    row = {
        "function": "one_line_near",
        "work_bucket": "normalized-structural-near-match",
        "subcategory": "near-zero-normalized-structural-residual",
        "primary_intervention": "normalized-residual-attribution",
        "secondary_signals": ["near-zero-structural-residual"],
        "evidence_stage": "observed",
        "blocker_families": ["residual-attribution"],
        "classification": {
            "structural_truth_gate": {
                "status": "near-zero-structural-diff",
                "normalized_diff_lines": 1,
            }
        },
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": "safe-v1-placeholder",
        "semantic_delta_families": ["address-constant-materialization"],
        "opcode_edit_direction": "substitution",
    }

    result = run_taxonomy_validator(tmp_path, row)

    assert result.returncode != 0
    assert "normalized trigger is unavailable" in result.stderr


def test_taxonomy_pages_validator_checks_exact_bss_root_cause_impacts(
    tmp_path: Path,
) -> None:
    def bss_row(function: str, key: str, impact: int) -> dict[str, object]:
        symbol = key.removeprefix("bss-symbol:")
        return {
            "function": function,
            "work_bucket": "data-symbol-relocation",
            "subcategory": "bss-section-anchor-ceiling",
            "primary_intervention": "bss-anchor-analysis",
            "secondary_signals": ["bss-section-anchor"],
            "evidence_stage": "blocked",
            "blocker_families": ["no-source-candidate"],
            "classification": {
                "bss_anchor_relocations": {
                    "pairs": [
                        {"kind": "R_PPC_ADDR16_HA", "named_symbol": symbol},
                        {"kind": "R_PPC_ADDR16_LO", "named_symbol": symbol},
                    ]
                }
            },
            "root_cause_keys": [key],
            "max_root_cause_impact": impact,
        }

    valid = [
        bss_row("shared_a", "bss-symbol:A", 2),
        bss_row("shared_b", "bss-symbol:A", 2),
        bss_row("singleton", "bss-symbol:B", 1),
        {
            "function": "legacy_non_bss",
            "work_bucket": "register-allocator",
            "subcategory": "register-only-needs-pcdump-proof",
            "primary_intervention": "register-allocation-proof",
            "secondary_signals": [],
            "evidence_stage": "observed",
            "blocker_families": ["allocator-proof"],
        },
    ]
    result = run_taxonomy_validator(tmp_path / "valid", valid)
    assert result.returncode == 0, result.stderr

    missing = [dict(row) for row in valid]
    missing[0].pop("root_cause_keys")
    result = run_taxonomy_validator(tmp_path / "missing", missing)
    assert result.returncode != 0
    assert "root_cause_keys" in result.stderr

    mismatched = [dict(row) for row in valid]
    mismatched[0]["max_root_cause_impact"] = 3
    result = run_taxonomy_validator(tmp_path / "mismatched", mismatched)
    assert result.returncode != 0
    assert "root cause impact" in result.stderr


def test_taxonomy_pages_validator_derives_bss_keys_from_structured_evidence(
    tmp_path: Path,
) -> None:
    base = {
        "function": "structured_bss",
        "work_bucket": "data-symbol-relocation",
        "subcategory": "bss-section-anchor-ceiling",
        "primary_intervention": "bss-anchor-analysis",
        "secondary_signals": ["bss-section-anchor"],
        "evidence_stage": "blocked",
        "blocker_families": ["no-source-candidate"],
        "classification": {
            "reasons": ["task #999 must not become a root-cause key"],
            "bss_anchor_relocations": {
                "pairs": [
                    {"kind": "R_PPC_ADDR16_HA", "named_symbol": "A"},
                    {"kind": "R_PPC_ADDR16_LO", "named_symbol": "A"},
                ]
            },
        },
        "root_cause_keys": ["bss-symbol:A"],
        "max_root_cause_impact": 1,
    }
    valid = run_taxonomy_validator(tmp_path / "valid", base)
    assert valid.returncode == 0, valid.stderr

    for name, keys in (
        ("wrong-symbol", ["bss-symbol:B"]),
        ("trailing-space", ["bss-symbol:A "]),
        ("duplicate", ["bss-symbol:A", "bss-symbol:A"]),
        ("issue-prose", ["bss-symbol:task #999"]),
    ):
        row = dict(base)
        row["root_cause_keys"] = keys
        result = run_taxonomy_validator(tmp_path / name, row)
        assert result.returncode != 0
        assert "structured BSS evidence" in result.stderr
