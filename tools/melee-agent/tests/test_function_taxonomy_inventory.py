from __future__ import annotations

import csv
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


def assert_no_deprecated_frame_keys(value: object) -> None:
    if isinstance(value, dict):
        assert "closability_tier" not in value
        assert "frame_closability_tier" not in value
        for nested in value.values():
            assert_no_deprecated_frame_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_deprecated_frame_keys(nested)


def write_report(path: Path) -> None:
    report = {
        "units": [
            {
                "name": "main/melee/demo/demo",
                "metadata": {
                    "source_path": "src/melee/demo/demo.c",
                    "complete": False,
                },
                "functions": [
                    {
                        "name": "matched_fn",
                        "size": "12",
                        "fuzzy_match_percent": 100.0,
                        "metadata": {"virtual_address": "2147483648"},
                    },
                    {
                        "name": "stack_fn",
                        "size": "384",
                        "fuzzy_match_percent": 99.75,
                        "metadata": {"virtual_address": "2147483660"},
                    },
                    {
                        "name": "small_fn",
                        "size": "180",
                        "fuzzy_match_percent": 99.5,
                        "metadata": {"virtual_address": "2147484044"},
                    },
                    {
                        "name": "frame_fn",
                        "size": "420",
                        "fuzzy_match_percent": 99.25,
                        "metadata": {"virtual_address": "2147484100"},
                    },
                    {
                        "name": "same_frame_fn",
                        "size": "420",
                        "fuzzy_match_percent": 99.125,
                        "metadata": {"virtual_address": "2147484112"},
                    },
                    {
                        "name": "broken_fn",
                        "size": "96",
                        "fuzzy_match_percent": 98.0,
                        "metadata": {"virtual_address": "2147484224"},
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(report), encoding="utf-8")


def fake_checkdiff(function: str):
    payloads = {
        "stack_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-slot-layout",
                "stack_slot_localizer": {
                    "frame_size": 64,
                    "mismatch_count": 2,
                    "deltas": [4],
                },
                "reasons": [
                    "opcode sequence matches; differences are operands, registers, labels, or offsets",
                    "2 differing paired lines reference stack slots",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 2},
            "reference_lines": 20,
            "current_lines": 20,
        },
        "small_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "operand-register-or-offset",
                "reasons": [
                    "opcode sequence matches; differences are operands, registers, labels, or offsets",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
            "reference_lines": 8,
            "current_lines": 8,
        },
        "frame_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-layout",
                "reasons": [
                    "frame reservation gap is too large; source-actionable transform unavailable",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
            "reference_lines": 32,
            "current_lines": 32,
        },
        "same_frame_fn": {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-layout",
                "stack_frame_delta": {
                    "expected_frame_size": 64,
                    "current_frame_size": 64,
                    "missing_stack_bytes": 0,
                },
                "reasons": [
                    "frame reservation gap is too large; stale checkdiff-only reason",
                ],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
            "reference_lines": 32,
            "current_lines": 32,
        },
    }
    if function == "broken_fn":
        return 1, "", "error: could not find broken_fn in compiled object"
    return 1, json.dumps(payloads[function]), "checkdiff stderr"


def fake_decl_order_evaluator(candidate, _record):
    if candidate.function == "frame_fn":
        raise AssertionError("frame-size residuals must not run decl-order probes")
    return {
        "evaluated_status": "evaluated",
        "candidate_count": 3,
        "evaluated_candidate_count": 3,
        "skipped_count": 0,
        "best_decl_delta": 0.125,
        "best_ordering": "swap a <-> b",
        "baseline_pct": candidate.match_percent,
        "best_pct": candidate.match_percent + 0.125,
        "scope": candidate.function,
        "selected_scope_reason": "function-top",
    }


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_opcode_delta_inventory_artifacts(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/opcode",
                        "metadata": {
                            "source_path": "src/melee/demo/opcode.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "generic_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483648"},
                            },
                            {
                                "name": "control_fn",
                                "size": "128",
                                "fuzzy_match_percent": 98.0,
                                "metadata": {"virtual_address": "2147483776"},
                            },
                            {
                                "name": "generic_renamed",
                                "size": "128",
                                "fuzzy_match_percent": 97.5,
                                "metadata": {"virtual_address": "2147483904"},
                            },
                            {
                                "name": "near_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147484032"},
                            },
                            {
                                "name": "near_renamed",
                                "size": "128",
                                "fuzzy_match_percent": 97.0,
                                "metadata": {"virtual_address": "2147484160"},
                            },
                            {
                                "name": "near_singleton",
                                "size": "128",
                                "fuzzy_match_percent": 96.5,
                                "metadata": {"virtual_address": "2147484288"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str) -> tuple[int, str, str]:
        if function.startswith("generic"):
            classification = {
                "primary": "instruction-sequence",
                "reasons": [f"identity-specific note for {function}"],
            }
        elif function.startswith("near"):
            classification = {
                "primary": "normalized-structural-near-match",
                "reasons": [f"identity-specific note for {function}"],
                "structural_truth_gate": {
                    "status": "near-zero-structural-diff",
                    "normalized_diff_lines": 1,
                },
            }
        else:
            classification = {"primary": "control-flow-source-shape"}
        if function.startswith("near"):
            target_asm = ["+000: mr r3, r4", "+004: blr"]
            current_opcode = "addi" if function == "near_singleton" else "li"
            current_asm = [f"+000: {current_opcode} r3, r3, 1", "+004: blr"]
        else:
            target_asm = [
                "+000: 80 83 00 00  lwz r4, 0(r3)",
                "lbl_80000004:",
                "/* 0004 */ addi r3, r3, 4",
                "+008: addi r3, r3, 4",
                "+00c: R_PPC_ADDR16_HA lbl_80300000",
                "+010: blr",
            ]
            current_asm = [
                "+000: 90 83 00 00  stw r4, 0(r3)",
                "<current+0x4>:",
                "/* 0004 */ ori r3, r3, 4",
                "+008: ori r3, r3, 4",
                "+00c: R_PPC_ADDR16_HA lbl_80400000",
                "+010: blr",
            ]
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": classification,
                "target_asm": target_asm,
                "current_asm": current_asm,
                "structural": {"opcode_similarity": 0.6},
            }
        ), ""

    output = tmp_path / "taxonomy"
    generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        workers=1,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        include_terminal_attempts=False,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    generic = next(row for row in records if row["function"] == "generic_fn")
    generic_renamed = next(
        row for row in records if row["function"] == "generic_renamed"
    )
    near = next(row for row in records if row["function"] == "near_fn")
    near_renamed = next(row for row in records if row["function"] == "near_renamed")
    near_singleton = next(
        row for row in records if row["function"] == "near_singleton"
    )
    control = next(row for row in records if row["function"] == "control_fn")
    assert generic["work_bucket"] == "structural-reconstruction"
    assert generic["subcategory"] == "opcode-sequence-diff"
    assert generic["opcode_delta_signature_status"] == "available"
    assert generic["opcode_delta_signature"] == (
        '{"dominant":[["addi","ori",2],["lwz","stw",1]],'
        '"first":["lwz","stw"],"version":1}'
    )
    assert generic["semantic_delta_families"] == [
        "address-constant-materialization",
        "integer-memory-width-transfer",
    ]
    assert generic["opcode_edit_direction"] == "substitution"
    assert near["work_bucket"] == "normalized-structural-near-match"
    assert near["subcategory"] == "near-zero-normalized-structural-residual"
    assert near["opcode_delta_signature_status"] == "available"
    assert near["semantic_delta_families"] == [
        "address-constant-materialization"
    ]
    assert near["opcode_edit_direction"] == "substitution"
    assert near["normalized_trigger_signature_status"] == "available"
    assert near["normalized_trigger_signature"] == (
        '{"edit_direction":"substitution","normalized_diff_lines":1,'
        '"pairs":[["mr","li"]],"version":1}'
    )
    assert near["normalized_trigger_family"] == "one-line-substitution"
    assert near["normalized_trigger_cluster_size"] == 2
    assert near_renamed["normalized_trigger_cluster_size"] == 2
    assert near_singleton["normalized_trigger_cluster_size"] == 1
    semantic_fields = (
        "opcode_delta_signature_status",
        "opcode_delta_signature",
        "semantic_delta_families",
        "opcode_edit_direction",
    )
    assert {field: generic[field] for field in semantic_fields} == {
        field: generic_renamed[field] for field in semantic_fields
    }
    near_semantic_fields = (*semantic_fields, "normalized_trigger_signature_status", "normalized_trigger_signature", "normalized_trigger_family")
    assert {field: near[field] for field in near_semantic_fields} == {
        field: near_renamed[field] for field in near_semantic_fields
    }
    assert "opcode_delta_signature" not in control

    queue = read_tsv(
        output / "queues" / "structural-reconstruction.opcode-sequence-diff.tsv"
    )
    assert [row["function"] for row in queue] == [
        "generic_fn",
        "generic_renamed",
    ]
    assert queue[0]["opcode_delta_signature"] == generic["opcode_delta_signature"]
    assert "opcode_delta_signature_status" in queue[0]
    semantic_columns = {
        "semantic_delta_families",
        "opcode_edit_direction",
        "normalized_trigger_signature_status",
        "normalized_trigger_signature",
        "normalized_trigger_family",
        "normalized_trigger_cluster_size",
    }
    assert semantic_columns <= set(queue[0])
    with (output / "taxonomy.records.csv").open(newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    csv_generic = next(row for row in csv_rows if row["function"] == "generic_fn")
    assert semantic_columns <= set(csv_generic)
    assert json.loads(csv_generic["semantic_delta_families"]) == generic[
        "semantic_delta_families"
    ]
    near_queue = read_tsv(
        output / "queues" / "normalized-structural-near-match.tsv"
    )
    near_queue_row = next(row for row in near_queue if row["function"] == "near_fn")
    assert json.loads(near_queue_row["semantic_delta_families"]) == near[
        "semantic_delta_families"
    ]
    assert json.loads(near_queue_row["normalized_trigger_signature"]) == {
        "edit_direction": "substitution",
        "normalized_diff_lines": 1,
        "pairs": [["mr", "li"]],
        "version": 1,
    }
    assert not list((output / "queues").glob("*lwz*stw*.tsv"))
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "structural-reconstruction.opcode-sequence-diff.tsv" in summary
    assert "lwz-stw" not in summary

    from tools.function_taxonomy_dashboard import generate_dashboard

    dashboard_data = generate_dashboard(output).dashboard_data_js
    dashboard_payload = json.loads(
        dashboard_data.read_text(encoding="utf-8")
        .removeprefix("window.__TAXONOMY_DASHBOARD_DATA__ = ")
        .removesuffix(";\n")
    )
    dashboard_record = next(
        row
        for row in dashboard_payload["records"]
        if row["function"] == "generic_fn"
    )
    assert dashboard_record["opcode_delta_signature"] == generic[
        "opcode_delta_signature"
    ]
    assert (
        "structural-reconstruction.opcode-sequence-diff.tsv"
        in dashboard_payload["taxonomyManifest"]["queueFiles"]
    )


def test_normalized_trigger_cluster_sizes_are_route_local_and_order_independent() -> None:
    from tools.function_taxonomy_inventory import (
        attach_normalized_trigger_cluster_sizes,
    )

    shared = '{"edit_direction":"substitution","normalized_diff_lines":1,"pairs":[["mr","li"]],"version":1}'
    different = '{"edit_direction":"substitution","normalized_diff_lines":1,"pairs":[["mr","addi"]],"version":1}'
    records = [
        {
            "function": "near_a",
            "work_bucket": "normalized-structural-near-match",
            "normalized_trigger_signature_status": "available",
            "normalized_trigger_signature": shared,
        },
        {
            "function": "near_b",
            "work_bucket": "normalized-structural-near-match",
            "normalized_trigger_signature_status": "available",
            "normalized_trigger_signature": shared,
        },
        {
            "function": "near_c",
            "work_bucket": "normalized-structural-near-match",
            "normalized_trigger_signature_status": "available",
            "normalized_trigger_signature": different,
        },
        {
            "function": "copied_elsewhere",
            "work_bucket": "structural-reconstruction",
            "normalized_trigger_signature_status": "available",
            "normalized_trigger_signature": shared,
        },
    ]
    reversed_records = [dict(row) for row in reversed(records)]

    attach_normalized_trigger_cluster_sizes(records)
    attach_normalized_trigger_cluster_sizes(reversed_records)

    assert {
        row["function"]: row.get("normalized_trigger_cluster_size") for row in records
    } == {
        "near_a": 2,
        "near_b": 2,
        "near_c": 1,
        "copied_elsewhere": None,
    }
    assert {
        row["function"]: row.get("normalized_trigger_cluster_size")
        for row in reversed_records
    } == {
        "near_a": 2,
        "near_b": 2,
        "near_c": 1,
        "copied_elsewhere": None,
    }


def test_root_cause_key_derivation_uses_only_structured_bss_symbols() -> None:
    from tools.function_taxonomy_inventory.root_cause import derive_root_cause_keys

    classification = {
        "reasons": ["issue #481 says fake_symbol should be grouped"],
        "bss_anchor_relocations": {
            "status": "ceiling",
            "pairs": [
                {
                    "kind": "R_PPC_ADDR16_HA",
                    "named_symbol": " lbl_80472ED8 ",
                    "anchor_symbol": "...bss.0",
                },
                {
                    "kind": "R_PPC_ADDR16_LO",
                    "named_symbol": "lbl_80472ED8",
                    "anchor_symbol": "...bss.0",
                },
                {
                    "kind": "R_PPC_ADDR16_HA",
                    "named_symbol": "ifStatus_HudInfo",
                    "anchor_symbol": "...bss.0",
                },
                {"named_symbol": "   "},
                {"named_symbol": 481},
                "malformed-pair",
            ],
        },
    }

    assert derive_root_cause_keys(classification) == [
        "bss-symbol:lbl_80472ED8",
        "bss-symbol:ifStatus_HudInfo",
    ]
    renamed = dict(classification)
    renamed["function"] = "task_481_fake_symbol"
    renamed["reasons"] = ["completely different prose"]
    assert derive_root_cause_keys(renamed) == derive_root_cause_keys(classification)
    assert derive_root_cause_keys(None) == []
    assert derive_root_cause_keys({"bss_anchor_relocations": {"pairs": "bad"}}) == []


def test_root_cause_impacts_are_unique_per_row_and_order_independent() -> None:
    from tools.function_taxonomy_inventory.root_cause import (
        attach_root_cause_impacts,
    )

    records = [
        {"function": "a", "root_cause_keys": ["bss-symbol:A"]},
        {
            "function": "ab",
            "root_cause_keys": ["bss-symbol:A", "bss-symbol:B"],
        },
        {
            "function": "bb",
            "root_cause_keys": ["bss-symbol:B", "bss-symbol:B"],
        },
        {"function": "empty", "root_cause_keys": []},
        {"function": "malformed", "root_cause_keys": "bss-symbol:A"},
        {"function": "legacy"},
    ]
    reversed_records = [dict(row) for row in reversed(records)]

    attach_root_cause_impacts(records)
    attach_root_cause_impacts(reversed_records)

    expected = {"a": 2, "ab": 2, "bb": 2, "empty": 0}
    assert {
        row["function"]: row["max_root_cause_impact"]
        for row in records
        if "max_root_cause_impact" in row
    } == expected
    assert {
        row["function"]: row["max_root_cause_impact"]
        for row in reversed_records
        if "max_root_cause_impact" in row
    } == expected
    assert "max_root_cause_impact" not in records[4]
    assert "max_root_cause_impact" not in records[5]


def test_semantic_delta_fixed_queues_are_overlapping_route_local_and_ordered(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import (
        write_normalized_trigger_cluster_queue,
        write_queue,
        write_semantic_opcode_family_queues,
        write_summary,
    )
    from tools.function_taxonomy_schema import (
        SEMANTIC_DELTA_FAMILY_ORDER,
        build_dashboard_manifest,
    )

    shared_signature = '{"edit_direction":"substitution","normalized_diff_lines":1,"pairs":[["mr","li"]],"version":1}'
    generic_multi = {
        "function": "generic_multi",
        "work_bucket": "structural-reconstruction",
        "subcategory": "opcode-sequence-diff",
        "match_percent": 99.0,
        "semantic_delta_families": [
            "address-constant-materialization",
            "integer-memory-width-transfer",
        ],
        "opcode_edit_direction": "mixed",
    }
    generic_one = {
        "function": "generic_one",
        "work_bucket": "structural-reconstruction",
        "subcategory": "opcode-sequence-diff",
        "match_percent": 98.0,
        "semantic_delta_families": ["frame-save-window"],
        "opcode_edit_direction": "substitution",
    }
    near_high = {
        "function": "near_high",
        "work_bucket": "normalized-structural-near-match",
        "subcategory": "near-zero-normalized-structural-residual",
        "match_percent": 99.5,
        "semantic_delta_families": ["address-constant-materialization"],
        "opcode_edit_direction": "substitution",
        "normalized_trigger_signature_status": "available",
        "normalized_trigger_signature": shared_signature,
        "normalized_trigger_family": "one-line-substitution",
        "normalized_trigger_cluster_size": 2,
    }
    near_low = {**near_high, "function": "near_low", "match_percent": 97.0}
    near_singleton = {
        **near_high,
        "function": "near_singleton",
        "normalized_trigger_signature": shared_signature.replace('"li"', '"addi"'),
        "normalized_trigger_cluster_size": 1,
    }
    control_copy = {
        **generic_multi,
        "function": "control_copy",
        "subcategory": "branch-or-control-flow-shape",
    }
    records = [
        generic_multi,
        generic_one,
        near_low,
        near_high,
        near_singleton,
        control_copy,
    ]
    queues = tmp_path / "queues"
    queues.mkdir()
    write_queue(
        queues / "structural-reconstruction.opcode-sequence-diff.tsv",
        [generic_multi, generic_one],
    )
    write_queue(
        queues / "normalized-structural-near-match.tsv",
        [near_high, near_low, near_singleton],
    )

    write_semantic_opcode_family_queues(queues, records)
    write_normalized_trigger_cluster_queue(queues, records)

    family_files = [
        queues / f"structural-reconstruction.opcode-family.{family}.tsv"
        for family in SEMANTIC_DELTA_FAMILY_ORDER
    ]
    assert all(path.exists() for path in family_files)
    assert [
        row["function"]
        for row in read_tsv(
            queues
            / "structural-reconstruction.opcode-family.address-constant-materialization.tsv"
        )
    ] == ["generic_multi"]
    assert [
        row["function"]
        for row in read_tsv(
            queues
            / "structural-reconstruction.opcode-family.integer-memory-width-transfer.tsv"
        )
    ] == ["generic_multi"]
    assert [
        row["function"]
        for row in read_tsv(
            queues / "structural-reconstruction.opcode-family.frame-save-window.tsv"
        )
    ] == ["generic_one"]
    assert read_tsv(
        queues / "structural-reconstruction.opcode-family.other-opcode-sequence.tsv"
    ) == []
    cluster_path = queues / "normalized-structural-near-match.trigger-clusters.tsv"
    assert [row["function"] for row in read_tsv(cluster_path)] == [
        "near_high",
        "near_low",
    ]
    for path in [*family_files, cluster_path]:
        header = path.read_text(encoding="utf-8").splitlines()[0].split("\t")
        assert header[:2] == ["function", "work_bucket"]
        assert {
            "semantic_delta_families",
            "opcode_edit_direction",
            "normalized_trigger_signature_status",
            "normalized_trigger_signature",
            "normalized_trigger_family",
            "normalized_trigger_cluster_size",
        } <= set(header)
    assert not any(any(char in path.name for char in "{}[]") for path in queues.iterdir())

    queue_counts = {
        path.name: len(read_tsv(path)) for path in queues.glob("*.tsv")
    }
    manifest = build_dashboard_manifest(records, queue_counts)
    expected_queue_order = [
        "structural-reconstruction.opcode-sequence-diff.tsv",
        *[
            f"structural-reconstruction.opcode-family.{family}.tsv"
            for family in SEMANTIC_DELTA_FAMILY_ORDER
        ],
        "normalized-structural-near-match.tsv",
        "normalized-structural-near-match.trigger-clusters.tsv",
    ]
    assert manifest["queueFiles"] == expected_queue_order

    summary_path = tmp_path / "summary.md"
    write_summary(
        summary_path,
        report_non100_count=len(records),
        records=records,
        errors=[],
    )
    summary = summary_path.read_text(encoding="utf-8")
    assert all(filename in summary for filename in expected_queue_order)


def test_repeated_bss_root_cause_queue_and_summary_are_fixed_and_ordered(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import (
        write_repeated_bss_root_cause_queue,
        write_summary,
    )
    from tools.function_taxonomy_schema import build_dashboard_manifest

    def bss_row(
        function: str, key: str, impact: int, match_percent: float
    ) -> dict[str, object]:
        return {
            "function": function,
            "work_bucket": "data-symbol-relocation",
            "subcategory": "bss-section-anchor-ceiling",
            "match_percent": match_percent,
            "root_cause_keys": [key],
            "max_root_cause_impact": impact,
        }

    records = [
        bss_row("shared_low", "bss-symbol:A", 3, 97.0),
        bss_row("shared_high", "bss-symbol:A", 3, 99.0),
        bss_row("pair_b", "bss-symbol:B", 2, 98.0),
        bss_row("singleton", "bss-symbol:C", 1, 99.5),
        {
            **bss_row("copied_non_bss", "bss-symbol:A", 3, 99.9),
            "work_bucket": "register-allocator",
            "subcategory": "register-only-needs-pcdump-proof",
        },
    ]
    queues = tmp_path / "queues"
    queues.mkdir()

    write_repeated_bss_root_cause_queue(queues, records)

    queue_path = queues / "root-cause.bss-symbol.repeated.tsv"
    assert [row["function"] for row in read_tsv(queue_path)] == [
        "shared_high",
        "shared_low",
        "pair_b",
    ]
    header = queue_path.read_text(encoding="utf-8").splitlines()[0].split("\t")
    assert header[:2] == ["function", "work_bucket"]
    assert {"root_cause_keys", "max_root_cause_impact"} <= set(header)
    assert all(symbol not in queue_path.name for symbol in ("A", "B", "C"))

    summary_path = tmp_path / "summary.md"
    write_summary(
        summary_path,
        report_non100_count=len(records),
        records=records,
        errors=[],
    )
    summary = summary_path.read_text(encoding="utf-8")
    assert "## Repeated BSS Root-Cause Keys" in summary
    assert "| bss-symbol:A | 2 |" in summary
    assert "| bss-symbol:B | 1 |" not in summary
    assert "root-cause.bss-symbol.repeated.tsv" in summary

    manifest = build_dashboard_manifest(
        records,
        {
            "data-symbol-relocation.tsv": 4,
            "root-cause.bss-symbol.repeated.tsv": 3,
        },
    )
    assert manifest["queueFiles"] == [
        "data-symbol-relocation.tsv",
        "root-cause.bss-symbol.repeated.tsv",
    ]


def write_control_flow_report(path: Path, function: str = "control_fn") -> None:
    path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/control",
                        "metadata": {
                            "source_path": "src/melee/demo/control.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": function,
                                "size": "128",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483648"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def control_flow_checkdiff(function: str) -> tuple[int, str, str]:
    return 1, json.dumps(
        {
            "function": function,
            "match": False,
            "classification": {
                "primary": "control-flow-source-shape",
                "reasons": ["control-flow/source shape differs"],
                "indexed_struct_pointer_materialization": {
                    "expected_indexed_ops": ["lwz r7, 0x10(r6)"],
                    "current_materialized_pointers": ["lwz r7, 0(r3)"],
                },
            },
            "target_asm": [
                "/* 0000 */ cmpwi r3, 0",
                "/* 0004 */ bne lbl_true",
                "/* 0008 */ li r0, 0",
                "/* 000C */ b lbl_done",
                "lbl_true:",
                "/* 0010 */ li r0, 1",
                "lbl_done:",
                "/* 0014 */ mulli r5, r4, 0x24",
                "/* 0018 */ add r6, r3, r5",
                "/* 001C */ lwz r7, 0x10(r6)",
            ],
            "current_asm": [
                "/* 0000 */ subfic r0, r3, 0",
                "/* 0004 */ cntlzw r0, r0",
                "/* 0008 */ srwi r0, r0, 5",
                "/* 000C */ bl fn_803AC168",
                "/* 0010 */ lwz r7, 0(r3)",
            ],
            "structural": {"opcode_similarity": 0.8, "line_delta": 5, "hunk_count": 2},
            "reference_lines": 10,
            "current_lines": 5,
        }
    ), ""


def write_control_flow_source(path: Path, function: str = "control_fn") -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        """\
typedef unsigned char u8;
typedef struct HSD_JObj HSD_JObj;
typedef struct MnVibrationData {
    u8 x0[6];
    HSD_JObj* jobjs[25];
} MnVibrationData;
static u8 mnVibration_804D4FE8[4];

void {function}(MnVibrationData* data)
{
    int i;
    HSD_JObj* panel_jobj;
    for (i = 0; i < 4; i++) {
        panel_jobj = data->jobjs[mnVibration_804D4FE8[(u8)i]];
    }
}
""".replace("{function}", function),
        encoding="utf-8",
    )


def generate_control_flow_inventory(
    report: Path,
    output: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    generate_inventory(
        report,
        output,
        checkdiff_runner=control_flow_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        workers=1,
        include_terminal_attempts=False,
    )


def test_generate_inventory_control_flow_shape_enriches_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    source_root = tmp_path / "repo"
    write_control_flow_report(report)
    write_control_flow_source(source_root / "src/melee/demo/control.c")
    monkeypatch.setattr(inventory, "REPO_ROOT", source_root)

    generate_control_flow_inventory(report, output)

    record = read_jsonl(output / "taxonomy.records.jsonl")[0]
    assert record["work_bucket"] == "structural-reconstruction"
    assert record["subcategory"] == "branch-or-control-flow-shape"
    assert record["confidence"] == "heuristic"
    assert record["source_actionability"] == "structural-rebuild"
    assert record["control_flow_shape_analysis_status"] == "heuristic-hints"
    assert len(record["control_flow_shape_hints"]) >= 2
    assert record["control_flow_shape_hint_kinds"] == list(
        dict.fromkeys(item["kind"] for item in record["control_flow_shape_hints"])
    )
    assert all(isinstance(item["evidence"], dict) for item in record["control_flow_shape_hints"])
    assert record["control_flow_shape_validation_status"] == "not-run"
    assert record["control_flow_shape_validated_probe_count"] == 0
    assert record["control_flow_shape_source_preflight_status"] == "materializable"
    assert record["control_flow_shape_generated_probe_count"] > 0
    assert record["next_command"].startswith("melee-agent debug mutate control-flow-shape-search")


def test_generate_inventory_control_flow_shape_source_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_control_flow_report(report)
    monkeypatch.setattr(inventory, "REPO_ROOT", tmp_path / "missing-repo")

    generate_control_flow_inventory(report, output)

    record = read_jsonl(output / "taxonomy.records.jsonl")[0]
    assert record["work_bucket"] == "structural-reconstruction"
    assert record["control_flow_shape_source_preflight_status"] == "source-unavailable"
    assert record["control_flow_shape_generated_probe_count"] == 0
    assert record["control_flow_shape_blockers"] == ["source-unavailable"]
    assert record["control_flow_shape_validation_status"] == "not-run"
    assert record["control_flow_shape_validated_probe_count"] == 0


def test_generate_inventory_control_flow_shape_analysis_error_preserves_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.mwcc_debug.suggest_control_flow_shape as suggest
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_control_flow_report(report)
    monkeypatch.setattr(inventory, "REPO_ROOT", tmp_path / "repo")

    def raise_analysis(**_kwargs):
        raise RuntimeError("analyzer exploded")

    monkeypatch.setattr(suggest, "analyze_control_flow_shape", raise_analysis)
    generate_control_flow_inventory(report, output)

    record = read_jsonl(output / "taxonomy.records.jsonl")[0]
    assert record["work_bucket"] == "structural-reconstruction"
    assert record["control_flow_shape_analysis_status"] == "analysis-error"
    assert record["control_flow_shape_source_preflight_status"] == "no-hints"
    assert record["control_flow_shape_hints"] == []


def test_generate_inventory_control_flow_shape_preflight_error_preserves_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.mwcc_debug.suggest_control_flow_shape as suggest
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    source_root = tmp_path / "repo"
    write_control_flow_report(report)
    write_control_flow_source(source_root / "src/melee/demo/control.c")
    monkeypatch.setattr(inventory, "REPO_ROOT", source_root)

    def raise_preflight(*_args, **_kwargs):
        raise RuntimeError("preflight exploded")

    monkeypatch.setattr(suggest, "annotate_source_materialization", raise_preflight)
    generate_control_flow_inventory(report, output)

    record = read_jsonl(output / "taxonomy.records.jsonl")[0]
    assert record["work_bucket"] == "structural-reconstruction"
    assert record["control_flow_shape_hints"]
    assert record["control_flow_shape_source_preflight_status"] == "preflight-error"
    assert record["control_flow_shape_blockers"] == ["source-preflight-error"]


def test_control_flow_shape_queue_exports_fixed_materializable_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    source_root = tmp_path / "repo"
    write_control_flow_report(report)
    write_control_flow_source(source_root / "src/melee/demo/control.c")
    monkeypatch.setattr(inventory, "REPO_ROOT", source_root)

    generate_control_flow_inventory(report, output)

    record = read_jsonl(output / "taxonomy.records.jsonl")[0]
    kind = record["control_flow_shape_hint_kinds"][0]
    kind_queue = output / "queues" / f"structural-reconstruction.control-flow-shape.{kind}.tsv"
    queued = read_tsv(kind_queue)
    assert [row["function"] for row in queued] == ["control_fn"]
    assert json.loads(queued[0]["control_flow_shape_hint_kinds"]) == record[
        "control_flow_shape_hint_kinds"
    ]

    materializable = read_tsv(
        output / "queues" / "structural-reconstruction.control-flow-shape.materializable.tsv"
    )
    assert materializable[0]["control_flow_shape_validation_status"] == "not-run"
    terminal = output / "queues" / "structural-reconstruction.control-flow-shape.terminal.tsv"
    assert terminal.read_text(encoding="utf-8").count("\n") == 1
    assert not list((output / "queues").glob("*source-unavailable*.tsv"))


def test_control_flow_shape_queue_exports_terminal_proofs_without_blocker_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    source_root = tmp_path / "repo"
    write_control_flow_report(report, function="terminal_fn")
    write_control_flow_source(source_root / "src/melee/demo/control.c", "terminal_fn")
    (source_root / "src/melee/demo/control.c").write_text(
        "void terminal_fn(void)\n{\n    int x;\n    x = 0;\n}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(inventory, "REPO_ROOT", source_root)

    def terminal_checkdiff(function: str) -> tuple[int, str, str]:
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "control-flow-source-shape",
                    "reasons": ["loop shape differs"],
                },
                "target_asm": [
                    "/* 0000 */ lwz r4, 0(r3)",
                    "/* 0004 */ addi r3, r3, 0x24",
                    "/* 0008 */ lwz r4, 0(r3)",
                    "/* 000C */ addi r3, r3, 0x24",
                    "/* 0010 */ mtctr r5",
                    "lbl_loop:",
                    "/* 0014 */ lwz r4, 0(r3)",
                    "/* 0018 */ addi r3, r3, 0x24",
                    "/* 001C */ bdnz lbl_loop",
                ],
                "current_asm": [
                    "/* 0000 */ mtctr r5",
                    "lbl_loop:",
                    "/* 0004 */ lwz r4, 0(r3)",
                    "/* 0008 */ addi r3, r3, 0x24",
                    "/* 000C */ bdnz lbl_loop",
                ],
                "structural": {"opcode_similarity": 0.8, "line_delta": 5},
            }
        ), ""

    inventory.generate_inventory(
        report,
        output,
        checkdiff_runner=terminal_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        workers=1,
        include_terminal_attempts=False,
    )

    record = read_jsonl(output / "taxonomy.records.jsonl")[0]
    assert record["control_flow_shape_source_preflight_status"] == "terminal"
    assert record["control_flow_shape_source_preflight_reason"] == (
        "no safe loop-init or loop-peel source variant matched"
    )
    loop_queue = output / "queues" / "structural-reconstruction.control-flow-shape.loop-peel-unroll.tsv"
    assert [row["function"] for row in read_tsv(loop_queue)] == ["terminal_fn"]
    terminal = read_tsv(
        output / "queues" / "structural-reconstruction.control-flow-shape.terminal.tsv"
    )
    assert terminal[0]["function"] == "terminal_fn"
    assert json.loads(terminal[0]["control_flow_shape_blockers"]) == record[
        "control_flow_shape_blockers"
    ]
    assert not list((output / "queues").glob("*simple-counted-loop-not-found*.tsv"))


def write_data_symbol_report(path: Path, functions: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/data",
                        "metadata": {
                            "source_path": "src/melee/demo/data.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": function,
                                "size": "128",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {
                                    "virtual_address": str(2147483648 + index * 16)
                                },
                            }
                            for index, function in enumerate(functions)
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def data_symbol_checkdiff(function: str):
    return 1, json.dumps(
        {
            "function": function,
            "match": False,
            "classification": {
                "primary": "data-symbol-or-relocation",
                "reasons": ["data/symbol relocation mismatch"],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0},
        }
    ), ""


def test_generate_inventory_classifies_report_functions_and_writes_outputs(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=fake_checkdiff,
        decl_order_evaluator=fake_decl_order_evaluator,
        frame_report_runner=None,
        workers=1,
    )

    assert result.report_non100_count == 5
    assert result.classified_count == 4
    assert result.error_count == 1

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert [row["function"] for row in records] == [
        "stack_fn",
        "small_fn",
        "frame_fn",
        "same_frame_fn",
    ]
    assert records[0]["file_path"] == "melee/demo/demo.c"
    assert records[0]["address"] == "0x8000000c"
    assert records[0]["match_tier"] == ">=99%"
    assert records[0]["work_bucket"] == "stack-local-layout"
    assert records[0]["subcategory"] == "same-frame-stack-slot-placement"
    assert records[0]["frame_cause"] == "stack-object-offset-shift"
    assert records[0]["frame_evidence"] == "checkdiff-only"
    assert records[0]["frame_probe_status"] == "needs-attribution"
    assert "frame_closability_tier" not in records[0]
    assert records[0]["frame_match_relevance"] == "match-neutral"
    assert "same-frame stack-slot" in records[0]["frame_match_relevance_reason"]
    assert records[0]["source_actionability"] == "diagnostic-only"
    assert records[0]["headline_tool"] == "frame-reservations"
    assert records[0]["decl_order_summary"]["best_decl_delta"] == 0.125
    assert records[0]["decl_order_summary"]["best_ordering"] == "swap a <-> b"
    assert records[0]["decl_order_best_delta"] == 0.125
    assert records[0]["decl_order_best_ordering"] == "swap a <-> b"
    assert records[0]["decl_order_evaluated_status"] == "evaluated"
    assert records[0]["decl_order_candidate_count"] == 3
    assert records[1]["known_small_pattern_candidate"] is True
    assert records[1]["work_bucket"] == "known-small-pattern-candidate"
    assert records[1]["source_actionability"] == "manual-small-pattern"
    assert records[1]["headline_tool"] == "mismatch-db"
    assert "no source-emitting harvest harness" in records[1]["actionability_reason"]
    assert records[2]["work_bucket"] == "stack-local-layout"
    assert records[2]["subcategory"] == "frame-too-large"
    assert records[2]["frame_cause"] == "frame-too-large"
    assert records[2]["frame_evidence"] == "checkdiff-only"
    assert records[2]["frame_probe_status"] == "needs-attribution"
    assert records[2]["source_actionability"] == "diagnostic-only"
    assert records[2]["headline_tool"] == "frame-reservations"
    assert "#366" not in records[2]["actionability_reason"]
    assert "decl_order_summary" not in records[2]
    assert "debug dump local" in records[2]["next_command"]
    assert records[3]["work_bucket"] == "stack-local-layout"
    assert records[3]["subcategory"] == "same-frame-stack-slot-placement"
    assert records[3]["frame_cause"] == "stack-object-offset-shift"
    assert records[3]["frame_evidence"] == "checkdiff-only"
    assert records[3]["frame_probe_status"] == "needs-attribution"
    assert records[3]["headline_tool"] == "frame-reservations"
    assert "debug dump local" in records[3]["next_command"]

    errors = read_jsonl(output / "checkdiff-errors.jsonl")
    assert errors[0]["function"] == "broken_fn"
    assert "could not find broken_fn" in errors[0]["message"]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    from src.attempt_evidence import TERMINAL_ATTEMPT_FIELDS
    from tools.function_taxonomy_inventory import CONTROL_FLOW_SHAPE_SUMMARY_FIELDS

    assert (
        "function\twork_bucket\tmatch_percent\tprimary\tsubcategory\t"
            "primary_intervention\tsecondary_signals\tevidence_stage\t"
            "blocker_families\t"
            "opcode_delta_signature_status\topcode_delta_signature\t"
            "semantic_delta_families\topcode_edit_direction\t"
            "normalized_trigger_signature_status\t"
            "normalized_trigger_signature\tnormalized_trigger_family\t"
            "normalized_trigger_cluster_size\t"
            "root_cause_keys\tmax_root_cause_impact\t"
            "offset_discrepancy_count\toffset_discrepancy_bases\t"
        "offset_discrepancy_disps\toffset_discrepancy_opcodes\t"
        "struct_verify_status\tstruct_verify_finding_count\t"
        "struct_verify_verified_count\tstruct_verify_structs\t"
        "struct_verify_fields\tstruct_verify_skipped\t"
        "struct_verify_reason\t"
        "frame_cause\tframe_verdict\tframe_evidence\tframe_probe_status\t"
        "frame_match_relevance\tframe_match_relevance_reason\t"
        "frame_attribution_status\tframe_source_object_symbol\t"
        "cast_audit_status\tcast_medium_plus_count\t"
            "source_actionability\theadline_tool\tactionability_reason\t"
            + "\t".join(CONTROL_FLOW_SHAPE_SUMMARY_FIELDS) + "\t"
            + "\t".join(TERMINAL_ATTEMPT_FIELDS) + "\t"
            "decl_order_best_delta\tdecl_order_best_ordering\t"
            "decl_order_evaluated_status\tdecl_order_candidate_count\t"
            "name_magic_blocker\tname_magic_stop_kind\t"
            "name_magic_probe_count\tname_magic_reason\t"
            "file_path\tframe_next_command\tnext_command"
        ) in stack_queue
    header = stack_queue.splitlines()[0].split("\t")
    assert header.index("control_flow_shape_analysis_status") > header.index(
        "actionability_reason"
    )
    assert header.index("control_flow_shape_validation_status") < header.index(
        TERMINAL_ATTEMPT_FIELDS[0]
    )
    queue_rows = list(csv.DictReader(stack_queue.splitlines(), delimiter="\t"))
    stack_row = next(row for row in queue_rows if row["function"] == "stack_fn")
    assert stack_row["frame_evidence"] == "checkdiff-only"
    assert stack_row["frame_probe_status"] == "needs-attribution"
    assert stack_row["source_actionability"] == "diagnostic-only"
    assert "\t0.12500\tswap a <-> b\tevaluated\t3" in stack_queue
    frame_row = next(row for row in queue_rows if row["function"] == "frame_fn")
    assert frame_row["frame_evidence"] == "checkdiff-only"
    assert frame_row["frame_probe_status"] == "needs-attribution"
    assert frame_row["source_actionability"] == "diagnostic-only"

    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "| Report unmatched functions | 5 |" in summary
    assert "| stack-local-layout | 3 |" in summary
    assert "| known-small-pattern-candidate | 1 |" in summary
    assert (
        "`build/function-taxonomy/queues/"
        "data-symbol-relocation.no-name-magic-candidate.tsv`"
    ) in summary


def test_equal_stack_frame_summary_routes_to_unattributed_lifetime_ordering() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_candidate

    candidate = FunctionCandidate(
        function="equal_frame_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=420,
        match_percent=99.4,
        address="0x80000000",
        object_status="NonMatching",
    )

    def runner(function: str) -> tuple[int, str, str]:
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "stack-layout",
                    "stack_frame_sizes": {
                        "expected_frame_size": 120,
                        "current_frame_size": 120,
                        "frame_growth": 0,
                    },
                    "offset_discrepancies": [],
                    "reasons": [
                        "normalized structural diff is zero",
                        "2 differing paired lines reference stack slots",
                    ],
                },
                "structural": {
                    "opcode_similarity": 1.0,
                    "line_delta": 0,
                    "hunk_count": 3,
                },
            }
        ), ""

    record, error = classify_candidate(
        candidate,
        runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "stack-local-layout"
    assert record["subcategory"] == "unattributed-lifetime-or-ordering-shift"
    assert record["frame_cause"] == "lifetime-or-ordering-shift"
    assert record["frame_probe_status"] == "needs-attribution"
    assert record["source_actionability"] == "diagnostic-only"
    assert "frame-size residual" not in record["actionability_reason"]
    assert "debug dump local" in record["next_command"]


def test_generate_inventory_no_longer_overlays_terminal_attempt_evidence(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    ledger = tmp_path / "attempt_ledger.json"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/indexed",
                        "metadata": {
                            "source_path": "src/melee/demo/indexed.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "indexed_fn",
                                "size": "256",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483648"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": {
                    "indexed_fn": {
                        "function": "indexed_fn",
                        "move_on_recommended": True,
                        "move_on_reason": "repeated no-progress attempts",
                        "suspected_blocker": "no-safe-materialized-pointer",
                        "attempts": [
                            {
                                "index": 2,
                                "timestamp": 20.0,
                                "timestamp_utc": "2026-06-07T00:00:20+00:00",
                                "outcome": "blocked",
                                "classification": "indexed-struct-pointer",
                                "blocker": "no-safe-materialized-pointer",
                                "retained": False,
                                "note": "no source retained",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def indexed_checkdiff(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "indexed-struct-pointer-materialization",
                    "reasons": ["array indexed versus element pointer mismatch"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    generate_inventory(
        report,
        output,
        checkdiff_runner=indexed_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        workers=1,
        attempt_ledger_path=ledger,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert len(records) == 1
    record = records[0]
    assert record["work_bucket"] == "indexed-struct-pointer"
    assert record["primary"] == "indexed-struct-pointer-materialization"
    assert record["subcategory"] == "array-indexed-vs-element-pointer"
    assert isinstance(record["classification"], dict)
    assert isinstance(record["structural"], dict)
    assert isinstance(record["match"], float)
    # The attempt ledger no longer overlays terminal "dead end" evidence: the
    # record keeps its source-derived actionability and is not demoted, even
    # though the ledger entry recommends move-on with a known blocker.
    assert record["source_actionability"] == "current-tools-indexed-pointer"
    assert record["headline_tool"] == "source-shape"
    assert "terminal_attempt_status" not in record

    queue_rows = read_tsv(output / "queues" / "indexed-struct-pointer.tsv")
    assert len(queue_rows) == 1
    queue_row = queue_rows[0]
    assert queue_row["source_actionability"] == "current-tools-indexed-pointer"
    assert queue_row["headline_tool"] == "source-shape"
    # The terminal-attempt columns remain in the schema but are emitted empty.
    assert queue_row["terminal_attempt_status"] == ""
    assert queue_row["terminal_attempt_blocker"] == ""


def test_generate_inventory_can_disable_terminal_attempt_overlay(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    ledger = tmp_path / "attempt_ledger.json"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/indexed",
                        "metadata": {
                            "source_path": "src/melee/demo/indexed.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "indexed_fn",
                                "size": "256",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483648"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": {
                    "indexed_fn": {
                        "function": "indexed_fn",
                        "move_on_recommended": True,
                        "suspected_blocker": "no-safe-materialized-pointer",
                        "attempts": [
                            {
                                "index": 2,
                                "timestamp": 20.0,
                                "outcome": "blocked",
                                "blocker": "no-safe-materialized-pointer",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def indexed_checkdiff(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "indexed-struct-pointer-materialization",
                    "reasons": ["array indexed versus element pointer mismatch"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    generate_inventory(
        report,
        output,
        checkdiff_runner=indexed_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        workers=1,
        attempt_ledger_path=ledger,
        include_terminal_attempts=False,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert records[0]["source_actionability"] == "current-tools-indexed-pointer"
    assert records[0]["headline_tool"] == "source-shape"
    assert "terminal_attempt_status" not in records[0]


def test_generate_inventory_ignores_ledger_tool_fingerprints(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    ledger = tmp_path / "attempt_ledger.json"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/indexed",
                        "metadata": {
                            "source_path": "src/melee/demo/indexed.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "indexed_fn",
                                "size": "256",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483648"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": {
                    "indexed_fn": {
                        "function": "indexed_fn",
                        "move_on_recommended": True,
                        "suspected_blocker": "no-safe-materialized-pointer",
                        "attempts": [
                            {
                                "index": 2,
                                "timestamp": 20.0,
                                "outcome": "blocked",
                                "blocker": "no-safe-materialized-pointer",
                                "taxonomy_tool_sha256": "old-taxonomy-tool",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inventory, "_taxonomy_tool_sha256", lambda: "new-taxonomy-tool")

    def indexed_checkdiff(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "indexed-struct-pointer-materialization",
                    "reasons": ["array indexed versus element pointer mismatch"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    inventory.generate_inventory(
        report,
        output,
        checkdiff_runner=indexed_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        workers=1,
        attempt_ledger_path=ledger,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    record = records[0]
    assert record["source_actionability"] == "current-tools-indexed-pointer"
    assert record["headline_tool"] == "source-shape"
    # Terminal evidence is disabled, so tool-fingerprint staleness is moot: the
    # record is never overlaid regardless of the ledger's recorded fingerprint.
    assert "terminal_attempt_status" not in record
    assert "terminal_attempt_stale_check" not in record
    assert "terminal_attempt_taxonomy_tool_sha256" not in record


def test_generate_inventory_does_not_export_terminal_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    ledger = tmp_path / "attempt_ledger.json"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/indexed",
                        "metadata": {
                            "source_path": "src/melee/demo/indexed.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "indexed_fn",
                                "size": "256",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483648"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "functions": {
                    "indexed_fn": {
                        "function": "indexed_fn",
                        "move_on_recommended": True,
                        "suspected_blocker": "no-safe-materialized-pointer",
                        "attempts": [
                            {
                                "index": 2,
                                "timestamp": 20.0,
                                "outcome": "blocked",
                                "blocker": "no-safe-materialized-pointer",
                                "tooling_sha256": "old-tooling",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inventory, "_taxonomy_tool_sha256", lambda: "taxonomy-tool")

    def indexed_checkdiff(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "indexed-struct-pointer-materialization",
                    "reasons": ["array indexed versus element pointer mismatch"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    inventory.generate_inventory(
        report,
        output,
        checkdiff_runner=indexed_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        workers=1,
        attempt_ledger_path=ledger,
    )

    # Terminal evidence is disabled: ledger tool fingerprints are never copied
    # onto the record, and the queue's terminal columns stay empty.
    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert "terminal_attempt_tooling_sha256" not in records[0]

    queue_rows = read_tsv(output / "queues" / "indexed-struct-pointer.tsv")
    assert queue_rows[0]["terminal_attempt_tooling_sha256"] == ""


def test_generate_inventory_writes_completed_run_status_last(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=fake_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=2,
    )

    status_path = output / "run-status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["attempted_count"] == result.attempted_count == 2
    assert status["classified_count"] == result.classified_count == 2
    assert status["error_count"] == result.error_count == 0
    assert status["report_non100_count"] == result.report_non100_count == 5
    assert status["started_at"]
    assert status["completed_at"]
    assert "failed_at" not in status


def test_generate_inventory_marks_failed_status_when_classification_crashes(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    queues = output / "queues"
    queues.mkdir(parents=True)
    stale_queue = queues / "signature-call-type.tsv"
    stale_queue.write_text(
        "match_percent\tfunction\tnext_command\n"
        "99.0\told_fn\tmelee-agent debug suggest casts old_fn\n",
        encoding="utf-8",
    )
    write_report(report)

    def crashing_runner(function: str):
        raise RuntimeError(f"boom while classifying {function}")

    with pytest.raises(RuntimeError, match="boom while classifying stack_fn"):
        generate_inventory(
            report,
            output,
            checkdiff_runner=crashing_runner,
            decl_order_evaluator=None,
            frame_report_runner=None,
            workers=1,
            limit=1,
        )

    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["attempted_count"] == 1
    assert "boom while classifying stack_fn" in status["error"]
    assert status["started_at"]
    assert status["failed_at"]
    assert "completed_at" not in status
    assert "debug suggest casts old_fn" in stale_queue.read_text(encoding="utf-8")


def test_generate_inventory_marks_failed_status_when_report_load_fails(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "broken-report.json"
    output = tmp_path / "taxonomy"
    output.mkdir()
    (output / "run-status.json").write_text(
        json.dumps({"status": "completed", "completed_at": "old"}),
        encoding="utf-8",
    )
    report.write_text("{not-json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        generate_inventory(
            report,
            output,
            checkdiff_runner=fake_checkdiff,
            decl_order_evaluator=None,
            frame_report_runner=None,
            workers=1,
        )

    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["attempted_count"] == 0
    assert status["error_type"] == "JSONDecodeError"
    assert "completed_at" not in status


def test_generate_inventory_marks_failed_before_waiting_for_sibling_worker(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    slow_started = threading.Event()
    release_slow = threading.Event()
    worker_done = threading.Event()
    worker_errors: list[BaseException] = []

    def runner(function: str):
        if function == "stack_fn":
            raise RuntimeError("boom before sibling finishes")
        if function == "small_fn":
            slow_started.set()
            release_slow.wait(timeout=2)
        return fake_checkdiff(function)

    def invoke_inventory() -> None:
        try:
            with pytest.raises(RuntimeError, match="boom before sibling finishes"):
                generate_inventory(
                    report,
                    output,
                    checkdiff_runner=runner,
                    decl_order_evaluator=None,
                    frame_report_runner=None,
                    workers=2,
                    limit=2,
                )
        except BaseException as exc:
            worker_errors.append(exc)
        finally:
            worker_done.set()

    thread = threading.Thread(target=invoke_inventory)
    thread.start()
    try:
        assert slow_started.wait(timeout=1)
        status_path = output / "run-status.json"
        for _ in range(100):
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") == "failed":
                break
            threading.Event().wait(timeout=0.01)
        else:
            pytest.fail("inventory did not mark failed before sibling worker finished")
        assert status["error_type"] == "RuntimeError"
    finally:
        release_slow.set()
        thread.join(timeout=2)
    assert worker_errors == []
    assert worker_done.is_set()


def test_generate_inventory_consumes_later_completed_worker_before_slow_earlier_one(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    completed: list[str] = []
    small_done = threading.Event()

    def runner(function: str):
        if function == "stack_fn":
            assert small_done.wait(timeout=2)
        elif function == "small_fn":
            small_done.set()
        return fake_checkdiff(function)

    def progress(event: dict[str, object]) -> None:
        if event.get("event") == "candidate_done":
            completed.append(str(event["function"]))

    generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=2,
        limit=2,
        progress_callback=progress,
    )

    assert completed[:2] == ["small_fn", "stack_fn"]


def test_generate_inventory_emits_periodic_progress_when_workers_are_busy(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    events: list[dict[str, object]] = []

    def slow_runner(function: str):
        threading.Event().wait(timeout=0.05)
        return fake_checkdiff(function)

    generate_inventory(
        report,
        output,
        checkdiff_runner=slow_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=1,
        progress_callback=events.append,
        progress_interval=0.01,
    )

    progress_events = [
        event for event in events if event.get("event") == "inventory_progress"
    ]
    assert progress_events
    assert progress_events[0]["completed_count"] == 0
    assert progress_events[0]["pending_count"] == 1
    assert progress_events[0]["active_functions"] == ["stack_fn"]


def test_generate_inventory_emits_progress_during_steady_completion(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    events: list[dict[str, object]] = []

    def runner(function: str):
        threading.Event().wait(timeout=0.02)
        return fake_checkdiff(function)

    generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=4,
        progress_callback=events.append,
        progress_interval=0.03,
    )

    progress_events = [
        event for event in events if event.get("event") == "inventory_progress"
    ]
    assert progress_events
    assert any(int(event["completed_count"]) > 0 for event in progress_events)

    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"


def test_classify_candidate_restores_source_after_decl_order_side_effect(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import tools.function_taxonomy_inventory as inventory
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_candidate

    repo_root = tmp_path / "repo"
    source = repo_root / "src" / "melee" / "demo" / "demo.c"
    source.parent.mkdir(parents=True)
    original = "void same_frame_fn(void) { int stable = 0; }\n"
    mutated = "void same_frame_fn(void) { int leaked_decl_order = 1; }\n"
    source.write_text(original, encoding="utf-8")
    monkeypatch.setattr(inventory, "REPO_ROOT", repo_root)
    monkeypatch.setattr(inventory._common, "REPO_ROOT", repo_root)
    candidate = FunctionCandidate(
        function="same_frame_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=420,
        match_percent=99.125,
        address="0x80000000",
        object_status="NonMatching",
    )

    def mutating_decl_order_evaluator(candidate, _record):
        source.write_text(mutated, encoding="utf-8")
        return fake_decl_order_evaluator(candidate, _record)

    record, error = classify_candidate(
        candidate,
        fake_checkdiff,
        decl_order_evaluator=mutating_decl_order_evaluator,
        frame_report_runner=None,
        cast_audit_runner=None,
        struct_verify_runner=None,
    )

    assert error is None
    assert record is not None
    assert record["decl_order_evaluated_status"] == "evaluated"
    assert source.read_text(encoding="utf-8") == original


def test_classify_candidate_serializes_decl_order_snapshot_restore(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import tools.function_taxonomy_inventory as inventory
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_candidate

    repo_root = tmp_path / "repo"
    source = repo_root / "src" / "melee" / "demo" / "demo.c"
    source.parent.mkdir(parents=True)
    original = "void same_frame_fn(void) { int stable = 0; }\n"
    mutated_a = "void same_frame_fn(void) { int leaked_a = 1; }\n"
    mutated_b = "void same_frame_fn(void) { int leaked_b = 2; }\n"
    source.write_text(original, encoding="utf-8")
    monkeypatch.setattr(inventory, "REPO_ROOT", repo_root)
    monkeypatch.setattr(inventory._common, "REPO_ROOT", repo_root)

    def candidate(function: str) -> FunctionCandidate:
        return FunctionCandidate(
            function=function,
            unit="main/melee/demo/demo",
            file_path="melee/demo/demo.c",
            size_bytes=420,
            match_percent=99.125,
            address="0x80000000",
            object_status="NonMatching",
        )

    a_entered = threading.Event()
    b_entered = threading.Event()
    a_done = threading.Event()

    def same_frame_checkdiff(function: str):
        if function == "same_frame_b":
            assert a_entered.wait(timeout=5), "worker A never entered evaluator"
        payload = {
            "function": function,
            "match": False,
            "classification": {
                "primary": "stack-layout",
                "stack_frame_delta": {
                    "expected_frame_size": 64,
                    "current_frame_size": 64,
                    "missing_stack_bytes": 0,
                },
                "reasons": ["same frame; declaration order probe candidate"],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0, "hunk_count": 1},
            "reference_lines": 32,
            "current_lines": 32,
        }
        return 1, json.dumps(payload), "checkdiff stderr"

    def interleaving_decl_order_evaluator(candidate, record):
        if candidate.function == "same_frame_a":
            source.write_text(mutated_a, encoding="utf-8")
            a_entered.set()
            b_entered.wait(timeout=0.5)
        else:
            source.write_text(mutated_b, encoding="utf-8")
            b_entered.set()
            assert a_done.wait(timeout=5), "worker A never restored source"
        return fake_decl_order_evaluator(candidate, record)

    results = {}

    def run_a() -> None:
        try:
            results["a"] = classify_candidate(
                candidate("same_frame_a"),
                same_frame_checkdiff,
                decl_order_evaluator=interleaving_decl_order_evaluator,
                frame_report_runner=None,
                cast_audit_runner=None,
                struct_verify_runner=None,
            )
        finally:
            a_done.set()

    def run_b() -> None:
        results["b"] = classify_candidate(
            candidate("same_frame_b"),
            same_frame_checkdiff,
            decl_order_evaluator=interleaving_decl_order_evaluator,
            frame_report_runner=None,
            cast_audit_runner=None,
            struct_verify_runner=None,
        )

    thread_a = threading.Thread(target=run_a)
    thread_b = threading.Thread(target=run_b)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert results["a"][1] is None
    assert results["b"][1] is None
    assert source.read_text(encoding="utf-8") == original


def test_offset_discrepancies_do_not_override_root_cause_buckets() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_candidate

    candidate = FunctionCandidate(
        function="root_cause_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )

    expected = {
        "signature-type-mismatch": "signature-call-type",
        "inline-boundary-toolchain-artifact": "inline-boundary",
        "data-symbol-or-relocation": "data-symbol-relocation",
        "indexed-struct-pointer-materialization": "indexed-struct-pointer",
        "stack-slot-layout": "stack-local-layout",
        "stack-layout": "stack-local-layout",
        "register-allocation": "register-allocator",
        "control-flow-source-shape": "structural-reconstruction",
        "instruction-sequence": "structural-reconstruction",
    }

    for primary, bucket in expected.items():
        def runner(function: str, primary: str = primary):
            return 1, json.dumps(
                {
                    "function": function,
                    "match": False,
                    "classification": {
                        "primary": primary,
                        "offset_discrepancies": [
                            {
                                "base_reg": "r31",
                                "cur_disp": 260,
                                "ref_disp": 264,
                                "opcode": "lwz",
                            }
                        ],
                        "reasons": ["offset-only field displacement mismatch"],
                    },
                    "structural": {"opcode_similarity": 1.0, "line_delta": 0},
                }
            ), ""

        record, error = classify_candidate(
            candidate,
            runner,
            decl_order_evaluator=None,
            frame_report_runner=None,
            cast_audit_runner=(
                (lambda _candidate: {"medium_plus_count": 1})
                if primary == "signature-type-mismatch"
                else None
            ),
            struct_verify_runner=None,
        )

        assert error is None
        assert record is not None
        assert record["work_bucket"] == bucket


def test_offset_discrepancies_route_to_struct_offset_bucket_for_offset_residuals() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_candidate

    candidate = FunctionCandidate(
        function="struct_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )

    def runner(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "operand-register-or-offset",
                    "offset_discrepancies": [
                        {
                            "base_reg": "r31",
                            "cur_disp": 260,
                            "ref_disp": 264,
                            "opcode": "lwz",
                        }
                    ],
                    "reasons": ["offset-only field displacement mismatch"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    record, error = classify_candidate(
        candidate,
        runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        struct_verify_runner=None,
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["subcategory"] == "struct-field-offset-displacement"
    assert record["source_actionability"] == "current-tools-struct-verify"
    assert record["headline_tool"] == "struct-verify"
    assert record["offset_discrepancy_count"] == 1
    assert record["offset_discrepancy_bases"] == "r31"
    assert record["offset_discrepancy_disps"] == "current:260 expected:264"
    assert "melee-agent struct verify struct_fn" in record["next_command"]
    assert "--struct <struct-name>" not in record["next_command"]
    assert "--base r31" in record["next_command"]


def test_struct_verify_command_includes_unique_base() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, _struct_verify_command

    candidate = FunctionCandidate(
        function="struct_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )

    cmd = _struct_verify_command(
        candidate,
        {
            "offset_discrepancies": [
                {"base_reg": "r31", "cur_disp": 260, "ref_disp": 264},
            ],
        },
    )

    assert cmd == [
        "melee-agent",
        "struct",
        "verify",
        "struct_fn",
        "--base",
        "r31",
        "--tu-src",
        "src/melee/demo/demo.c",
        "--json",
    ]


def test_struct_verify_command_omits_base_for_multiple_bases() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, _struct_verify_command

    candidate = FunctionCandidate(
        function="struct_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )

    cmd = _struct_verify_command(
        candidate,
        {
            "offset_discrepancies": [
                {"base_reg": "r30", "cur_disp": 260, "ref_disp": 264},
                {"base_reg": "r31", "cur_disp": 260, "ref_disp": 264},
            ],
        },
    )

    assert "--base" not in cmd
    assert cmd == [
        "melee-agent",
        "struct",
        "verify",
        "struct_fn",
        "--tu-src",
        "src/melee/demo/demo.c",
        "--json",
    ]


def test_struct_verify_gate_summary_reports_verified_named_fields() -> None:
    from tools.function_taxonomy_inventory import summarize_struct_verify_payload

    summary = summarize_struct_verify_payload(
        {
            "findings": [
                {
                    "struct": "Fake",
                    "field": "x0",
                    "conflict": False,
                    "ambiguous": False,
                },
            ],
            "skipped": [],
        }
    )

    assert summary["struct_verify_status"] == "verified"
    assert summary["struct_verify_finding_count"] == 1
    assert summary["struct_verify_verified_count"] == 1
    assert summary["struct_verify_structs"] == "Fake"
    assert summary["struct_verify_fields"] == "x0"


def test_struct_verify_gate_summary_reports_unverified_for_resolver_negative() -> None:
    from tools.function_taxonomy_inventory import summarize_struct_verify_payload

    summary = summarize_struct_verify_payload(
        {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        }
    )

    assert summary["struct_verify_status"] == "unverified"
    assert summary["struct_verify_verified_count"] == 0
    assert "auto-struct unresolved" in summary["struct_verify_reason"]


def test_struct_verify_gate_summary_reports_unverified_for_ambiguous_or_conflicting() -> None:
    from tools.function_taxonomy_inventory import summarize_struct_verify_payload

    ambiguous = summarize_struct_verify_payload(
        {
            "findings": [
                {
                    "struct": "Fake",
                    "field": "x0",
                    "conflict": False,
                    "ambiguous": True,
                },
            ],
            "skipped": [],
        }
    )
    conflicting = summarize_struct_verify_payload(
        {
            "findings": [
                {
                    "struct": "Fake",
                    "field": "x0",
                    "conflict": True,
                    "ambiguous": False,
                },
            ],
            "skipped": [],
        }
    )

    assert ambiguous["struct_verify_status"] == "unverified"
    assert conflicting["struct_verify_status"] == "unverified"


def test_struct_verify_gate_summary_reports_unverified_for_missing_struct_or_field() -> None:
    from tools.function_taxonomy_inventory import summarize_struct_verify_payload

    summary = summarize_struct_verify_payload(
        {
            "findings": [
                {"struct": "Fake", "conflict": False, "ambiguous": False},
                {"field": "x0", "conflict": False, "ambiguous": False},
            ],
            "skipped": [],
        }
    )

    assert summary["struct_verify_status"] == "unverified"
    assert summary["struct_verify_finding_count"] == 2
    assert summary["struct_verify_verified_count"] == 0


def test_struct_verify_gate_summary_reports_unavailable_for_runner_or_checkdiff_failures() -> None:
    from tools.function_taxonomy_inventory import summarize_struct_verify_payload

    no_payload = summarize_struct_verify_payload(None)
    failed_checkdiff = summarize_struct_verify_payload(
        {
            "findings": [],
            "skipped": [["struct_fn", "checkdiff failed"]],
        }
    )

    assert no_payload["struct_verify_status"] == "unavailable"
    assert failed_checkdiff["struct_verify_status"] == "unavailable"
    assert "checkdiff failed" in failed_checkdiff["struct_verify_reason"]


def _offset_candidate_for_struct_verify_gate():
    from tools.function_taxonomy_inventory import FunctionCandidate

    return FunctionCandidate(
        function="struct_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )


def _offset_checkdiff_runner(function: str):
    return 1, json.dumps(
        {
            "function": function,
            "match": False,
            "classification": {
                "primary": "operand-register-or-offset",
                "offset_discrepancies": [
                    {"base_reg": "r31", "cur_disp": 260, "ref_disp": 264, "opcode": "lwz"},
                ],
                "reasons": ["offset-only field displacement mismatch"],
            },
            "structural": {"opcode_similarity": 1.0, "line_delta": 0},
        }
    ), ""


def test_struct_verify_gate_keeps_verified_struct_offset_bucket() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [
                {"struct": "Fake", "field": "x0", "conflict": False, "ambiguous": False},
            ],
            "skipped": [],
        },
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["confidence"] == "resolver-verified"
    assert record["struct_verify_status"] == "verified"
    assert record["struct_verify_verified_count"] == 1
    assert record["struct_verify_structs"] == "Fake"
    assert record["struct_verify_fields"] == "x0"


def test_struct_verify_gate_rebuckets_unverified_to_data_symbol() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        },
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "data-symbol-relocation"
    assert record["subcategory"] == "unverified-struct-offset-displacement"
    assert record["confidence"] == "resolver-rebucketed"
    assert record["source_actionability"] == "current-tools-data-symbol"
    assert record["headline_tool"] == "checkdiff-name-magic"
    assert record["offset_discrepancy_count"] == 1
    assert record["offset_discrepancy_bases"] == "r31"
    assert record["struct_verify_status"] == "unverified"


def test_struct_verify_gate_keeps_unavailable_in_heuristic_struct_bucket() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=lambda _candidate, _classification: None,
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["confidence"] == "heuristic"
    assert record["struct_verify_status"] == "unavailable"


def test_struct_verify_gate_none_preserves_legacy_struct_offset_behavior() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["confidence"] == "heuristic"
    assert "struct_verify_status" not in record


def test_struct_verify_gate_rebucket_runs_name_magic_preflight() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=lambda _candidate: {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "no-name-magic-candidate",
                "reason": "no source-addressable relocation pair",
            },
            "probe_count": 0,
        },
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        },
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "data-symbol-relocation"
    assert record["name_magic_blocker"] == "no-name-magic-candidate"
    assert record["source_actionability"] == "blocked-data-symbol-no-name-magic-candidate"


def test_struct_verify_negative_with_no_supported_data_pair_rehomes_displacement() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=lambda _candidate: {
            "blocker": "raw-diff-no-supported-data-symbol-pair",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "raw-diff-no-supported-data-symbol-pair",
                "reason": "raw diff contains no supported data-symbol pair",
            },
            "probe_count": 0,
            "probes": [],
        },
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        },
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["subcategory"] == "unresolved-operand-displacement"
    assert record["confidence"] == "resolver-unverified"
    assert record["source_actionability"] == "struct-inference-blocked"
    assert record["headline_tool"] == "struct-verify"
    assert record["struct_verify_status"] == "unverified"
    assert record["name_magic_blocker"] == "raw-diff-no-supported-data-symbol-pair"
    assert record["name_magic_probe_count"] == 0
    assert record["offset_discrepancy_count"] == 1
    assert "no supported data-symbol pair" in record["actionability_reason"]
    assert "struct verify" in record["next_command"]


def test_unresolved_displacement_facets_use_final_rehomed_route() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    record, error = classify_candidate(
        _offset_candidate_for_struct_verify_gate(),
        _offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=lambda _candidate: {
            "blocker": "raw-diff-no-supported-data-symbol-pair",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "raw-diff-no-supported-data-symbol-pair",
                "reason": "raw diff contains no supported data-symbol pair",
            },
            "probe_count": 0,
            "probes": [],
        },
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        },
    )

    assert error is None
    assert record is not None
    assert record["work_bucket"] == "struct-offset-discrepancy"
    assert record["primary_intervention"] == "struct-layout-inference"
    assert record["evidence_stage"] == "blocked"
    assert record["blocker_families"] == ["struct-inference"]
    assert "unresolved-struct-field" in record["secondary_signals"]


def test_inventory_exports_routing_facets_and_fixed_stage_queues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.function_taxonomy_inventory as inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    source_root = tmp_path / "repo"
    write_control_flow_report(report)
    write_control_flow_source(source_root / "src/melee/demo/control.c")
    monkeypatch.setattr(inventory, "REPO_ROOT", source_root)

    generate_control_flow_inventory(report, output)

    records = read_jsonl(output / "taxonomy.records.jsonl")
    for row in records:
        assert isinstance(row["primary_intervention"], str)
        assert isinstance(row["secondary_signals"], list)
        assert isinstance(row["evidence_stage"], str)
        assert isinstance(row["blocker_families"], list)

    csv_header = (output / "taxonomy.records.csv").read_text().splitlines()[0]
    queue_header = (
        output / "queues" / "stack-local-layout.tsv"
    ).read_text().splitlines()[0]
    assert queue_header.split("\t")[:2] == ["function", "work_bucket"]
    for field in (
        "work_bucket",
        "primary_intervention",
        "secondary_signals",
        "evidence_stage",
        "blocker_families",
    ):
        assert field in csv_header
        assert field in queue_header

    for stage in ("materializable", "validated", "blocked"):
        assert (output / "queues" / f"routing.{stage}.tsv").exists()

    row = read_tsv(
        output / "queues" / "structural-reconstruction.tsv"
    )[0]
    assert json.loads(row["secondary_signals"]) == records[0]["secondary_signals"]
    assert json.loads(row["blocker_families"]) == records[0]["blocker_families"]


def test_raw_diff_without_data_pair_does_not_rehome_native_data_symbol_row() -> None:
    from tools.function_taxonomy_inventory import (
        FunctionCandidate,
        attach_name_magic_preflight,
    )

    candidate = FunctionCandidate(
        function="native_data_fn",
        unit="main/melee/demo/data",
        file_path="melee/demo/data.c",
        size_bytes=128,
        match_percent=99.0,
        address="0x80000000",
        object_status="NonMatching",
    )
    record = {
        "work_bucket": "data-symbol-relocation",
        "subcategory": "persistent-data-symbol-or-relocation",
        "struct_verify_status": "",
    }
    attach_name_magic_preflight(
        record,
        candidate,
        {
            "blocker": "raw-diff-no-supported-data-symbol-pair",
            "probe_count": 0,
            "stop_condition": {
                "kind": "blocked",
                "reason": "no supported pair",
            },
        },
    )

    assert record["work_bucket"] == "data-symbol-relocation"
    assert record["subcategory"] == "persistent-data-symbol-or-relocation"
    assert record["source_actionability"] == (
        "blocked-data-symbol-raw-diff-no-supported-data-symbol-pair"
    )


def test_taxonomy_csv_and_queue_include_struct_verify_columns(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import write_csv, write_queue

    rows = [
        {
            "match_percent": 99.5,
            "function": "struct_fn",
            "work_bucket": "data-symbol-relocation",
            "primary": "operand-register-or-offset",
            "subcategory": "unverified-struct-offset-displacement",
            "struct_verify_status": "unverified",
            "struct_verify_verified_count": 0,
            "struct_verify_structs": "",
            "struct_verify_fields": "",
            "struct_verify_reason": "auto-struct unresolved: no source candidates",
        }
    ]

    csv_path = tmp_path / "records.csv"
    queue_path = tmp_path / "queue.tsv"
    write_csv(csv_path, rows)
    write_queue(queue_path, rows)

    csv_header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    queue_header = queue_path.read_text(encoding="utf-8").splitlines()[0]
    for header in (csv_header, queue_header):
        assert "struct_verify_status" in header
        assert "struct_verify_verified_count" in header
        assert "struct_verify_structs" in header
        assert "struct_verify_fields" in header
        assert "struct_verify_reason" in header


def test_generate_inventory_writes_struct_verify_evidence_to_queue(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/demo",
                        "metadata": {
                            "source_path": "src/melee/demo/demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "struct_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147483648"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=_offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [
                {"struct": "Fake", "field": "x0", "conflict": False, "ambiguous": False},
            ],
            "skipped": [],
        },
        workers=1,
    )

    assert result.classified_count == 1
    queue_text = (output / "queues" / "struct-offset-discrepancy.tsv").read_text(
        encoding="utf-8"
    )
    assert "struct_verify_status" in queue_text.splitlines()[0]
    assert "\tverified\t1\t1\tFake\tx0\t" in queue_text


def test_generate_inventory_rebucketed_unverified_struct_rows_land_in_data_symbol_queue(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/demo",
                        "metadata": {
                            "source_path": "src/melee/demo/demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "struct_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147483648"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=_offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        },
        workers=1,
    )

    assert result.classified_count == 1
    data_symbol_queue = (
        output / "queues" / "data-symbol-relocation.tsv"
    ).read_text(encoding="utf-8")
    struct_queue = (
        output / "queues" / "struct-offset-discrepancy.tsv"
    ).read_text(encoding="utf-8")
    assert "struct_fn" in data_symbol_queue
    assert "unverified-struct-offset-displacement" in data_symbol_queue
    assert "auto-struct unresolved: no source candidates" in data_symbol_queue
    assert "struct_fn" not in struct_queue


def test_unresolved_displacement_with_negative_data_preflight_uses_struct_queue(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/demo",
                        "metadata": {
                            "source_path": "src/melee/demo/demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "struct_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147483648"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    generate_inventory(
        report,
        output,
        checkdiff_runner=_offset_checkdiff_runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=lambda _candidate: {
            "blocker": "raw-diff-no-supported-data-symbol-pair",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "raw-diff-no-supported-data-symbol-pair",
                "reason": "raw diff contains no supported data-symbol pair",
            },
            "probe_count": 0,
            "probes": [],
        },
        struct_verify_runner=lambda _candidate, _classification: {
            "findings": [],
            "skipped": [["struct_fn", "auto-struct unresolved: no source candidates"]],
        },
        workers=1,
        include_terminal_attempts=False,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert records[0]["work_bucket"] == "struct-offset-discrepancy"
    assert records[0]["subcategory"] == "unresolved-operand-displacement"
    assert [
        row["function"]
        for row in read_tsv(output / "queues" / "struct-offset-discrepancy.tsv")
    ] == ["struct_fn"]
    assert read_tsv(output / "queues" / "data-symbol-relocation.tsv") == []
    assert read_tsv(
        output
        / "queues"
        / "data-symbol-relocation.raw-diff-no-supported-data-symbol-pair.tsv"
    ) == []


def test_default_struct_verify_runner_returns_none_for_subprocess_failures(monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    candidate = _offset_candidate_for_struct_verify_gate()

    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(inventory.subprocess, "run", lambda *args, **kwargs: Result())

    assert inventory.default_struct_verify_runner(candidate, {}) is None


def test_default_struct_verify_runner_returns_none_for_invalid_json(monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    candidate = _offset_candidate_for_struct_verify_gate()

    class Result:
        returncode = 0
        stdout = "not json"

    monkeypatch.setattr(inventory.subprocess, "run", lambda *args, **kwargs: Result())

    assert inventory.default_struct_verify_runner(candidate, {}) is None


def test_default_struct_verify_runner_returns_none_for_timeout(monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    candidate = _offset_candidate_for_struct_verify_gate()

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(inventory.subprocess, "run", timeout_run)

    assert inventory.default_struct_verify_runner(candidate, {}, timeout=1.0) is None


def test_fuzzy_100_noncomplete_functions_are_excluded_from_taxonomy(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/demo",
                        "metadata": {
                            "source_path": "src/melee/demo/demo.c",
                            "complete": False,
                        },
                        "measures": {
                            "matched_functions": 1,
                            "total_functions": 3,
                        },
                        "functions": [
                            {
                                "name": "fuzzy_exact",
                                "size": "64",
                                "fuzzy_match_percent": 100.0,
                                "metadata": {"virtual_address": "2147483648"},
                            },
                            {
                                "name": "fuzzy_offset",
                                "size": "64",
                                "fuzzy_match_percent": 100.0,
                                "metadata": {"virtual_address": "2147483712"},
                            },
                            {
                                "name": "unmatched_offset",
                                "size": "64",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147483744"},
                            },
                        ],
                    },
                    {
                        "name": "main/melee/demo/complete",
                        "metadata": {
                            "source_path": "src/melee/demo/complete.c",
                            "complete": True,
                        },
                        "functions": [
                            {
                                "name": "complete_fuzzy_100",
                                "size": "64",
                                "fuzzy_match_percent": 100.0,
                                "metadata": {"virtual_address": "2147483776"},
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    seen: list[str] = []

    def runner(function: str):
        seen.append(function)
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "operand-register-or-offset",
                    "offset_discrepancies": [
                        {
                            "base_reg": "r30",
                            "cur_disp": 12,
                            "ref_disp": 16,
                        }
                    ],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
    )

    assert seen == ["unmatched_offset"]
    assert result.report_non100_count == 1
    assert result.attempted_count == 1
    assert result.classified_count == 1
    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert [row["function"] for row in records] == ["unmatched_offset"]
    assert records[0]["work_bucket"] == "struct-offset-discrepancy"


def test_describe_actionability_splits_non_frame_work_buckets() -> None:
    from tools.function_taxonomy_inventory import describe_actionability

    cases = [
        (
            "known-small-pattern-candidate",
            "small-opcode-or-operand-pattern",
            "manual-small-pattern",
            "mismatch-db",
        ),
        (
            "signature-call-type",
            "call-shape-or-prototype",
            "advisory-signature-audit",
            "debug-suggest-signatures",
        ),
        (
            "inline-boundary",
            "missing-reference-call-current-inlined",
            "manual-inline-guidance",
            "patterns-inlines",
        ),
        (
            "data-symbol-relocation",
            "persistent-data-symbol-or-relocation",
            "current-tools-data-symbol",
            "checkdiff-name-magic",
        ),
        (
            "indexed-struct-pointer",
            "array-indexed-vs-element-pointer",
            "current-tools-indexed-pointer",
            "source-shape",
        ),
        (
            "struct-offset-discrepancy",
            "struct-field-offset-displacement",
            "current-tools-struct-verify",
            "struct-verify",
        ),
        (
            "structural-reconstruction",
            "branch-or-control-flow-shape",
            "structural-rebuild",
            "control-flow-shape-search",
        ),
        (
            "structural-reconstruction",
            "opcode-sequence-diff",
            "opcode-reconstruction",
            "opseq-mismatch-db",
        ),
        (
            "structural-reconstruction",
            "direct-inspection-needed",
            "backend-ceiling",
            "manual-inspection",
        ),
        (
            "backend-ceiling",
            "source-insensitive-backend-ceiling",
            "backend-ceiling",
            "manual-inspection",
        ),
        (
            "normalized-structural-near-match",
            "near-zero-normalized-structural-residual",
            "normalized-structural-triage",
            "manual-inspection",
        ),
        (
            "register-allocator",
            "register-only-needs-pcdump-proof",
            "pcdump-proof-needed",
            "mwcc-debug",
        ),
    ]

    for bucket, subcategory, actionability, headline in cases:
        result = describe_actionability(bucket, subcategory)
        assert result["source_actionability"] == actionability
        assert result["headline_tool"] == headline

    signature = describe_actionability("signature-call-type", "argument-bank")
    assert signature["source_actionability"] == "advisory-signature-audit"
    assert signature["headline_tool"] == "debug-suggest-signatures"
    assert "signature audit" in signature["actionability_reason"]

    equal_frame = describe_actionability(
        "stack-local-layout",
        "unattributed-lifetime-or-ordering-shift",
    )
    assert equal_frame["source_actionability"] == "diagnostic-only"
    assert equal_frame["headline_tool"] == "frame-reservations"
    assert "equal-size" in equal_frame["actionability_reason"]
    assert "frame-size residual" not in equal_frame["actionability_reason"]


@pytest.mark.parametrize(
    ("primary", "expected_bucket", "expected_subcategory", "expected_actionability"),
    [
        (
            "backend-ceiling",
            "backend-ceiling",
            "source-insensitive-backend-ceiling",
            "backend-ceiling",
        ),
        (
            "normalized-structural-near-match",
            "normalized-structural-near-match",
            "near-zero-normalized-structural-residual",
            "normalized-structural-triage",
        ),
    ],
)
def test_primary_specific_rows_do_not_collapse_into_structural_reconstruction(
    primary: str,
    expected_bucket: str,
    expected_subcategory: str,
    expected_actionability: str,
) -> None:
    from tools.function_taxonomy_inventory import (
        FunctionCandidate,
        classify_bucket,
        describe_actionability,
    )

    candidate = FunctionCandidate(
        function="taxonomy_primary_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.0,
        address="0x80000000",
        object_status="NonMatching",
    )
    bucket, subcategory, known_small = classify_bucket(
        candidate, {"classification": {"primary": primary}}
    )

    assert (bucket, subcategory, known_small) == (
        expected_bucket,
        expected_subcategory,
        False,
    )
    actionability = describe_actionability(bucket, subcategory)
    assert actionability["source_actionability"] == expected_actionability
    assert actionability["headline_tool"] == "manual-inspection"


@pytest.mark.parametrize(
    ("guidance", "expected_subcategory"),
    [
        (
            {
                "register_only_count": 8,
                "callee_swap_pairs": [["r27", "r28"]],
                "volatile_target_registers": [],
                "volatile_current_registers": [],
                "suggestions": ["callee-save source lifetime guidance"],
            },
            "callee-save-lifetime-ordering",
        ),
        (
            {
                "register_only_count": 4,
                "callee_swap_pairs": [],
                "volatile_target_registers": ["r4"],
                "volatile_current_registers": ["r0"],
                "suggestions": ["volatile target guidance"],
            },
            "volatile-register-selection",
        ),
        (
            {
                "register_only_count": 20,
                "callee_swap_pairs": [["r29", "r30"]],
                "volatile_target_registers": ["r3", "r4"],
                "volatile_current_registers": ["r3", "r4"],
                "suggestions": ["both guidance families"],
            },
            "callee-save-and-volatile-register-selection",
        ),
    ],
)
def test_normalized_structural_match_routes_register_guidance_to_allocator(
    guidance: dict[str, object],
    expected_subcategory: str,
) -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="normalized_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "normalized-structural-match",
            "register_allocation_guidance": guidance,
            "structural_truth_gate": {
                "status": "structural-match",
                "normalized_diff_lines": 0,
            },
            "offset_discrepancies": [],
            "reasons": ["normalized structural diff is zero"],
        },
        "structural": {"opcode_similarity": 1.0, "line_delta": 0},
    }

    assert classify_bucket(candidate, payload) == (
        "register-allocator",
        expected_subcategory,
        False,
    )


def test_normalized_structural_match_routes_relocation_only_residual_to_data() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="relocation_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "normalized-structural-match",
            "structural_truth_gate": {
                "status": "structural-match",
                "normalized_diff_lines": 0,
            },
            "offset_discrepancies": [],
            "reasons": [
                "normalized structural diff is zero",
                "2 differing paired lines reference data/symbol relocations",
            ],
        },
        "structural": {"opcode_similarity": 1.0, "line_delta": 0},
    }

    assert classify_bucket(candidate, payload) == (
        "data-symbol-relocation",
        "normalized-structural-relocation-only",
        False,
    )


def test_normalized_structural_match_without_specific_evidence_never_claims_reconstruction() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="unattributed_normalized_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "normalized-structural-match",
            "structural_truth_gate": {
                "status": "structural-match",
                "normalized_diff_lines": 0,
            },
            "offset_discrepancies": [],
            "reasons": ["normalized structural diff is zero"],
        }
    }

    assert classify_bucket(candidate, payload) == (
        "normalized-structural-near-match",
        "unattributed-zero-normalized-structural-residual",
        False,
    )


def test_primary_specific_rows_write_distinct_top_level_queues(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/demo",
                        "metadata": {
                            "source_path": "src/melee/demo/demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "backend_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147483648"},
                            },
                            {
                                "name": "near_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.0,
                                "metadata": {"virtual_address": "2147483664"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str):
        primary = {
            "backend_fn": "backend-ceiling",
            "near_fn": "normalized-structural-near-match",
        }[function]
        payload = {
            "function": function,
            "match": False,
            "classification": {
                "primary": primary,
                "reasons": ["taxonomy routing regression fixture"],
            },
            "structural": {"opcode_similarity": 0.99, "line_delta": 1},
        }
        return 1, json.dumps(payload), ""

    generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        workers=1,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
    )

    records = {row["function"]: row for row in read_jsonl(output / "taxonomy.records.jsonl")}
    assert records["backend_fn"]["work_bucket"] == "backend-ceiling"
    assert records["backend_fn"]["source_actionability"] == "backend-ceiling"
    assert records["near_fn"]["work_bucket"] == "normalized-structural-near-match"
    assert records["near_fn"]["source_actionability"] == "normalized-structural-triage"
    assert [row["function"] for row in read_tsv(output / "queues" / "backend-ceiling.tsv")] == [
        "backend_fn"
    ]
    assert [
        row["function"]
        for row in read_tsv(output / "queues" / "normalized-structural-near-match.tsv")
    ] == ["near_fn"]
    assert read_tsv(output / "queues" / "structural-reconstruction.tsv") == []


def test_signature_call_type_next_command_routes_to_signature_audit() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, next_command

    candidate = FunctionCandidate(
        function="fn_80000000",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        address="0x80000000",
        size_bytes=128,
        match_percent=98.5,
        object_status="NonMatching",
    )

    command = next_command("signature-call-type", "argument-bank", candidate)

    assert command == (
        "melee-agent debug suggest signatures -f fn_80000000 "
        "--source-file src/melee/demo/demo.c --json"
    )


def test_signature_call_type_next_command_omits_empty_source_file() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, next_command

    candidate = FunctionCandidate(
        function="fn_80000000",
        unit="main/melee/demo/demo",
        file_path="",
        address="0x80000000",
        size_bytes=128,
        match_percent=98.5,
        object_status="NonMatching",
    )

    command = next_command("signature-call-type", "argument-bank", candidate)

    assert command == "melee-agent debug suggest signatures -f fn_80000000 --json"


def test_bss_anchor_classification_buckets_as_ceiling() -> None:
    from tools.function_taxonomy_inventory import (
        FunctionCandidate,
        classify_bucket,
        describe_actionability,
    )

    candidate = FunctionCandidate(
        function="fn_80181C80",
        unit="main/melee/gm/gm_1A36",
        file_path="melee/gm/gm_1A36.c",
        size_bytes=220,
        match_percent=99.5,
        address="0x80181c80",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "instruction-sequence",
            "bss_anchor_relocations": {
                "status": "ceiling",
                "pairs": [
                    {
                        "offset": "004",
                        "kind": "R_PPC_ADDR16_HA",
                        "named_symbol": "lbl_80472ED8",
                        "anchor_symbol": "...bss.0",
                        "named_side": "expected",
                    }
                ],
            },
        }
    }

    bucket, subcategory, small = classify_bucket(candidate, payload)

    assert (bucket, subcategory, small) == (
        "data-symbol-relocation",
        "bss-section-anchor-ceiling",
        False,
    )
    actionability = describe_actionability(bucket, subcategory)
    assert actionability["source_actionability"] == "ceiling"
    assert actionability["headline_tool"] == "checkdiff-name-magic"


def test_bss_root_cause_inventory_fields_and_delimited_artifacts(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/bss",
                        "metadata": {
                            "source_path": "src/melee/demo/bss.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": function,
                                "size": "64",
                                "fuzzy_match_percent": 99.0 - index,
                                "metadata": {
                                    "virtual_address": str(2147483648 + index * 64)
                                },
                            }
                            for index, function in enumerate(
                                (
                                    "bss_shared_a",
                                    "bss_shared_b",
                                    "bss_singleton",
                                    "bss_no_valid_symbol",
                                )
                            )
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str) -> tuple[int, str, str]:
        symbol = {
            "bss_singleton": "vmtx",
            "bss_no_valid_symbol": " ",
        }.get(function, "lbl_80472ED8")
        return 1, json.dumps(
            {
                "function": function,
                "match": False,
                "classification": {
                    "primary": "bss-anchor-ceiling",
                    "reasons": [f"task #999 must not affect {function}"],
                    "bss_anchor_relocations": {
                        "status": "ceiling",
                        "pairs": [
                            {
                                "kind": "R_PPC_ADDR16_HA",
                                "named_symbol": symbol,
                                "anchor_symbol": "...bss.0",
                            },
                            {
                                "kind": "R_PPC_ADDR16_LO",
                                "named_symbol": symbol,
                                "anchor_symbol": "...bss.0",
                            },
                        ],
                    },
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        workers=1,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
        include_terminal_attempts=False,
    )

    rows = {
        row["function"]: row
        for row in read_jsonl(output / "taxonomy.records.jsonl")
    }
    assert rows["bss_shared_a"]["root_cause_keys"] == [
        "bss-symbol:lbl_80472ED8"
    ]
    assert rows["bss_shared_b"]["max_root_cause_impact"] == 2
    assert rows["bss_singleton"]["root_cause_keys"] == ["bss-symbol:vmtx"]
    assert rows["bss_singleton"]["max_root_cause_impact"] == 1
    assert rows["bss_no_valid_symbol"]["root_cause_keys"] == []
    assert rows["bss_no_valid_symbol"]["max_root_cause_impact"] == 0
    assert all(row["work_bucket"] == "data-symbol-relocation" for row in rows.values())

    queue_rows = read_tsv(output / "queues" / "data-symbol-relocation.tsv")
    assert json.loads(queue_rows[0]["root_cause_keys"])[0].startswith("bss-symbol:")
    assert queue_rows[0]["max_root_cause_impact"] in {"1", "2"}
    with (output / "taxonomy.records.csv").open(newline="", encoding="utf-8") as f:
        csv_rows = list(csv.DictReader(f))
    assert {"root_cause_keys", "max_root_cause_impact"} <= set(csv_rows[0])
    assert [
        row["function"]
        for row in read_tsv(
            output / "queues" / "root-cause.bss-symbol.repeated.tsv"
        )
    ] == ["bss_shared_a", "bss_shared_b"]
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "| bss-symbol:lbl_80472ED8 | 2 |" in summary


def test_structural_branch_next_command_uses_control_flow_shape_search() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, next_command

    candidate = FunctionCandidate(
        function="demo_fn",
        unit="main/melee/demo",
        file_path="melee/demo.c",
        size_bytes=128,
        match_percent=97.0,
        address="0x80000000",
        object_status="NonMatching",
    )

    command = next_command(
        "structural-reconstruction",
        "branch-or-control-flow-shape",
        candidate,
    )

    assert "debug mutate control-flow-shape-search -f demo_fn" in command
    assert "--source-file src/melee/demo.c" in command
    assert "--compile-probes" in command
    assert "--json" in command


def test_known_small_pattern_queue_has_no_current_tools_harvest_rows(
    tmp_path: Path,
) -> None:
    from src.harvest import HarvestFilters, load_queue_rows
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    generate_inventory(
        report,
        output,
        checkdiff_runner=fake_checkdiff,
        decl_order_evaluator=fake_decl_order_evaluator,
        frame_report_runner=None,
        workers=1,
    )

    rows = load_queue_rows(
        output / "queues" / "known-small-pattern-candidate.tsv",
        work_bucket="known-small-pattern-candidate",
        repo_root=REPO_ROOT,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-small-pattern",)}
        ),
    )

    assert rows == []


def test_signature_queue_routes_to_advisory_audit_without_harness(
    tmp_path: Path,
) -> None:
    from src.harvest import HarvestFilters, load_queue_rows, select_harness

    queues = tmp_path / "queues"
    queues.mkdir()
    (queues / "signature-call-type.tsv").write_text(
        (
            "match_percent\tfunction\tprimary\tsubcategory\t"
            "source_actionability\theadline_tool\tactionability_reason\t"
            "file_path\tnext_command\n"
            "99.5\tsig_fn\tsignature-type-mismatch\tcall-shape-or-prototype\t"
            "advisory-signature-audit\tdebug-suggest-signatures\t"
            "signature audit rebucket guidance\tmelee/demo/demo.c\t"
            "melee-agent debug suggest signatures -f sig_fn "
            "--source-file src/melee/demo/demo.c --json\n"
        ),
        encoding="utf-8",
    )
    (queues / "inline-boundary.tsv").write_text(
        (
            "match_percent\tfunction\tprimary\tsubcategory\t"
            "source_actionability\theadline_tool\tactionability_reason\t"
            "file_path\tnext_command\n"
            "99.5\tinline_fn\tinline-boundary-toolchain-artifact\t"
            "missing-reference-call-current-inlined\tmanual-inline-guidance\t"
            "patterns-inlines\tmanual inline guidance\tmelee/demo/demo.c\t"
            "melee-agent patterns inlines src/melee/demo/demo.c\n"
        ),
        encoding="utf-8",
    )

    signature = load_queue_rows(
        queues / "signature-call-type.tsv",
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
        filters=HarvestFilters(
            where={"source_actionability": ("advisory-signature-audit",)}
        ),
    )
    assert len(signature) == 1
    assert signature[0].headline_tool == "debug-suggest-signatures"
    assert select_harness(signature[0]) is None

    assert (
        load_queue_rows(
            queues / "signature-call-type.tsv",
            work_bucket="signature-call-type",
            repo_root=REPO_ROOT,
            filters=HarvestFilters(
                where={"source_actionability": ("current-tools-signature-audit",)}
            ),
        )
        == []
    )

    assert (
        load_queue_rows(
            queues / "inline-boundary.tsv",
            work_bucket="inline-boundary",
            repo_root=REPO_ROOT,
            filters=HarvestFilters(
                where={"source_actionability": ("current-tools-inline",)}
            ),
        )
        == []
    )


def test_completed_inventory_signature_queue_routes_to_debug_suggest_signatures(
    tmp_path: Path,
) -> None:
    from src.harvest import preview_harvest_queue
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/signature_demo",
                        "metadata": {
                            "source_path": "src/melee/demo/signature_demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "signature_fn",
                                "size": "128",
                                "fuzzy_match_percent": 99.5,
                                "metadata": {"virtual_address": "2147487000"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "classification": {
                    "primary": "signature-type-mismatch",
                    "reasons": ["call shape differs after signature audit"],
                },
                "structural": {"opcode_similarity": 0.999, "line_delta": 0},
            }
        ), ""

    def cast_audit_runner(_candidate):
        return {
            "status": "ok",
            "medium_plus_count": 1,
            "high_count": 0,
            "medium_count": 1,
            "low_count": 0,
        }

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=cast_audit_runner,
        workers=1,
    )

    assert result.classified_count == 1
    status = json.loads((output / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"

    queue_text = (output / "queues" / "signature-call-type.tsv").read_text(
        encoding="utf-8"
    )
    assert "debug suggest signatures -f signature_fn" in queue_text
    assert "debug suggest casts" not in queue_text

    preview = preview_harvest_queue(
        output / "queues" / "signature-call-type.tsv",
        work_bucket="signature-call-type",
        repo_root=REPO_ROOT,
    )
    assert preview["sample"][0]["next_command"] == (
        "melee-agent debug suggest signatures -f signature_fn "
        "--source-file src/melee/demo/signature_demo.c --json"
    )


def test_generate_inventory_records_checkdiff_timeout_error(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)

    def timeout_checkdiff(function: str):
        if function == "stack_fn":
            raise subprocess.TimeoutExpired(
                cmd=["tools/checkdiff.py", function],
                timeout=1.5,
                output="partial stdout",
                stderr="partial stderr",
            )
        return fake_checkdiff(function)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=timeout_checkdiff,
        decl_order_evaluator=fake_decl_order_evaluator,
        frame_report_runner=None,
        workers=2,
        limit=1,
    )

    assert result.classified_count == 0
    assert result.error_count == 1
    errors = read_jsonl(output / "checkdiff-errors.jsonl")
    assert errors[0]["function"] == "stack_fn"
    assert errors[0]["error"] == "checkdiff_timeout"
    assert "timed out after 1.5s" in errors[0]["message"]
    assert "partial stdout" in errors[0]["stdout_tail"]
    assert "partial stderr" in errors[0]["stderr_tail"]


def _subprocess_contract_candidate():
    from tools.function_taxonomy_inventory import FunctionCandidate

    return FunctionCandidate(
        function="contract_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=128,
        match_percent=99.5,
        address="0x80000000",
        object_status="NonMatching",
    )


def _mismatch_json(function: str) -> str:
    return json.dumps(
        {
            "function": function,
            "match": False,
            "classification": {
                "primary": "instruction-sequence",
                "reasons": ["instruction sequence differs"],
            },
            "structural": {"opcode_similarity": 0.9, "line_delta": 2},
        }
    )


def test_classify_candidate_accepts_expected_mismatch_exit() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    candidate = _subprocess_contract_candidate()
    record, error = classify_candidate(
        candidate,
        lambda function: (1, _mismatch_json(function), "checkdiff warning"),
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
    )

    assert error is None
    assert record is not None
    assert record["primary"] == "instruction-sequence"


def test_classify_candidate_rejects_traceback_after_valid_json() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    candidate = _subprocess_contract_candidate()
    traceback_text = (
        "Traceback (most recent call last):\n"
        "  File \"tools/checkdiff.py\", line 4156, in main\n"
        "    subprocess.run([\"killall\", \"wine-preloader\"])\n"
        "FileNotFoundError: [Errno 2] No such file or directory: 'killall'\n"
    )
    record, error = classify_candidate(
        candidate,
        lambda function: (1, _mismatch_json(function), traceback_text),
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
    )

    assert record is None
    assert error is not None
    assert error["error"] == "checkdiff_crash"
    assert error["returncode"] == 1
    assert "FileNotFoundError" in error["message"]
    assert "killall" in error["stderr_tail"]


def test_classify_candidate_rejects_unexpected_exit_after_valid_json() -> None:
    from tools.function_taxonomy_inventory import classify_candidate

    candidate = _subprocess_contract_candidate()
    record, error = classify_candidate(
        candidate,
        lambda function: (2, _mismatch_json(function), "classifier aborted"),
        decl_order_evaluator=None,
        frame_report_runner=None,
        cast_audit_runner=None,
        name_magic_preflight_runner=None,
        struct_verify_runner=None,
    )

    assert record is None
    assert error is not None
    assert error["error"] == "checkdiff_crash"
    assert "expected exit 1" in error["message"]


def test_default_decl_order_evaluator_reports_timeout(monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    candidate = inventory.FunctionCandidate(
        function="stack_fn",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=384,
        match_percent=99.75,
        address="0x8000000c",
        object_status="NonMatching",
    )

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=kwargs.get("args") or args[0],
            timeout=kwargs.get("timeout"),
            output="decl stdout",
            stderr="decl stderr",
        )

    monkeypatch.setattr(inventory.subprocess, "run", timeout_run)

    summary = inventory.default_decl_order_evaluator(candidate, {})

    assert summary["evaluated_status"] == "unevaluated: decl-orders timed out"
    assert summary["candidate_count"] == 0
    assert summary["best_decl_delta"] is None
    assert "decl stdout" in summary["stdout_tail"]
    assert "decl stderr" in summary["stderr_tail"]


def test_signature_bucket_requires_medium_cast_evidence() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="ftDemo_80000000",
        unit="main/melee/demo/demo",
        file_path="melee/demo/demo.c",
        size_bytes=512,
        match_percent=99.1,
        address="0x80000000",
        object_status="NonMatching",
    )
    payload = {
        "classification": {
            "primary": "signature-type-mismatch",
            "reasons": ["call shape differs after alignment"],
        },
        "structural": {"opcode_similarity": 0.99, "line_delta": 2},
    }

    assert classify_bucket(candidate, payload, cast_audit={"medium_plus_count": 1}) == (
        "signature-call-type",
        "call-shape-or-prototype",
        False,
    )
    assert classify_bucket(candidate, payload, cast_audit={"medium_plus_count": 0}) == (
        "structural-reconstruction",
        "branch-or-control-flow-shape",
        False,
    )


def test_signature_red_herring_rebuckets_by_dominant_residual() -> None:
    from tools.function_taxonomy_inventory import FunctionCandidate, classify_bucket

    candidate = FunctionCandidate(
        function="ftCo_800CF6E8",
        unit="main/melee/ft/ftcommon",
        file_path="melee/ft/ftcommon.c",
        size_bytes=2048,
        match_percent=99.0,
        address="0x800cf6e8",
        object_status="NonMatching",
    )

    frame_payload = {
        "classification": {
            "primary": "signature-type-mismatch",
            "reasons": [
                "call shape differs; check prototypes",
                "frame reservation gap is too small",
            ],
            "stack_frame_delta": {"missing_stack_bytes": 32},
        },
        "structural": {"opcode_similarity": 0.98, "line_delta": 4},
    }
    assert classify_bucket(candidate, frame_payload, cast_audit={"medium_plus_count": 0}) == (
        "stack-local-layout",
        "frame-too-small",
        False,
    )

    data_payload = {
        "classification": {
            "primary": "signature-type-mismatch",
            "reasons": [
                "call shape differs; check prototypes",
                "578 differing paired lines reference data/symbol relocations",
            ],
        },
        "structural": {"opcode_similarity": 0.999, "line_delta": 1},
    }
    assert classify_bucket(candidate, data_payload, cast_audit={"medium_plus_count": 0}) == (
        "data-symbol-relocation",
        "signature-red-herring-data-symbol",
        False,
    )


def test_inventory_help_renders_literal_percent() -> None:
    from tools.function_taxonomy_inventory import build_arg_parser

    help_text = build_arg_parser().format_help()

    assert ">=99% stack-" in help_text
    assert "local-layout rows" in help_text
    assert "--skip-struct-verify-gate" in help_text
    assert "--struct-verify-timeout" in help_text
    assert "option_strings" not in help_text


def test_main_skip_struct_verify_gate_passes_no_runner(tmp_path: Path, monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    seen: dict[str, object] = {}

    def fake_generate_inventory(*args, **kwargs):
        seen.update(kwargs)
        return inventory.InventoryResult(
            report_non100_count=0,
            attempted_count=0,
            classified_count=0,
            error_count=0,
            output_dir=Path(args[1]).resolve(),
        )

    monkeypatch.setattr(inventory, "generate_inventory", fake_generate_inventory)

    rc = inventory.main(
        [
            "--report", str(tmp_path / "report.json"),
            "--output", str(tmp_path / "taxonomy"),
            "--skip-struct-verify-gate",
        ]
    )

    assert rc == 0
    assert seen["struct_verify_runner"] is None


def test_main_struct_verify_timeout_reaches_default_runner(tmp_path: Path, monkeypatch) -> None:
    from tools import function_taxonomy_inventory as inventory

    seen: dict[str, object] = {}

    def fake_default_struct_verify_runner(candidate, classification, *, timeout):
        seen["timeout"] = timeout
        return None

    def fake_generate_inventory(*args, **kwargs):
        runner = kwargs["struct_verify_runner"]
        candidate = inventory.FunctionCandidate(
            function="struct_fn",
            unit="main/melee/demo/demo",
            file_path="melee/demo/demo.c",
            size_bytes=128,
            match_percent=99.5,
            address="0x80000000",
            object_status="NonMatching",
        )
        runner(candidate, {})
        return inventory.InventoryResult(
            report_non100_count=0,
            attempted_count=0,
            classified_count=0,
            error_count=0,
            output_dir=Path(args[1]).resolve(),
        )

    monkeypatch.setattr(inventory, "default_struct_verify_runner", fake_default_struct_verify_runner)
    monkeypatch.setattr(inventory, "generate_inventory", fake_generate_inventory)

    rc = inventory.main(
        [
            "--report", str(tmp_path / "report.json"),
            "--output", str(tmp_path / "taxonomy"),
            "--struct-verify-timeout", "12.5",
        ]
    )

    assert rc == 0
    assert seen["timeout"] == 12.5


def test_generate_inventory_honors_limit_before_running_checkdiff(tmp_path: Path) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_report(report)
    seen: list[str] = []

    def runner(function: str):
        seen.append(function)
        return fake_checkdiff(function)

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
        limit=1,
    )

    assert result.report_non100_count == 5
    assert result.attempted_count == 1
    assert seen == ["stack_fn"]


def test_data_symbol_name_magic_preflight_rebuckets_non_candidate_rows(
    tmp_path: Path,
) -> None:
    from src.harvest import HarvestFilters, load_queue_rows, preview_harvest_queue
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_data_symbol_report(report, ["blocked_fn", "ready_fn"])

    def name_magic_preflight(candidate):
        if candidate.function == "ready_fn":
            return {
                "blocker": "no-name-magic-candidate",
                "stop_condition": {
                    "kind": "unvalidated",
                    "blocker": "no-name-magic-candidate",
                    "reason": "safe name-magic probes were generated but not compiled",
                },
                "probe_count": 1,
                "probes": [{"label": "data-symbol-static-to-global-0"}],
            }
        return {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "no-name-magic-candidate",
                "reason": "no source-addressable relocation pair",
            },
            "probe_count": 0,
            "probes": [],
        }

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=data_symbol_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        name_magic_preflight_runner=name_magic_preflight,
        workers=1,
    )

    assert result.classified_count == 2
    records = {row["function"]: row for row in read_jsonl(output / "taxonomy.records.jsonl")}
    assert records["blocked_fn"]["source_actionability"] == (
        "blocked-data-symbol-no-name-magic-candidate"
    )
    assert records["blocked_fn"]["name_magic_blocker"] == "no-name-magic-candidate"
    assert records["blocked_fn"]["name_magic_stop_kind"] == "blocked"
    assert records["blocked_fn"]["name_magic_probe_count"] == 0
    assert records["blocked_fn"]["name_magic_reason"] == (
        "no source-addressable relocation pair"
    )
    assert "no source-emitting name-magic candidate" in records[
        "blocked_fn"
    ]["actionability_reason"]
    assert records["ready_fn"]["source_actionability"] == "current-tools-data-symbol"
    assert records["ready_fn"]["name_magic_probe_count"] == 1

    main_queue = (output / "queues" / "data-symbol-relocation.tsv").read_text(
        encoding="utf-8"
    )
    assert "name_magic_blocker" in main_queue.splitlines()[0]
    assert "blocked-data-symbol-no-name-magic-candidate" in main_queue
    subqueue = (
        output / "queues" / "data-symbol-relocation.no-name-magic-candidate.tsv"
    ).read_text(encoding="utf-8")
    assert "blocked_fn" in subqueue
    assert "ready_fn" not in subqueue

    current_rows = load_queue_rows(
        output / "queues" / "data-symbol-relocation.tsv",
        work_bucket="data-symbol-relocation",
        repo_root=REPO_ROOT,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )
    assert [row.function for row in current_rows] == ["ready_fn"]
    preview = preview_harvest_queue(
        output / "queues" / "data-symbol-relocation.tsv",
        work_bucket="data-symbol-relocation",
        repo_root=REPO_ROOT,
        filters=HarvestFilters(
            where={"source_actionability": ("current-tools-data-symbol",)}
        ),
    )
    assert preview["sample"][0]["function"] == "ready_fn"
    assert preview["near_miss_facets"]["name_magic_blocker"] == [
        {"value": "no-name-magic-candidate", "count": 1}
    ]


@pytest.mark.parametrize(
    ("blocker", "expected_actionability"),
    [
        (
            "unsupported-source-site",
            "blocked-data-symbol-unsupported-source-site",
        ),
        (
            "ambiguous-relocation-pair",
            "blocked-data-symbol-ambiguous-relocation-pair",
        ),
        (
            "unsupported-reloc-kind",
            "blocked-data-symbol-unsupported-reloc-kind",
        ),
        (
            "raw-diff-no-supported-data-symbol-pair",
            "blocked-data-symbol-raw-diff-no-supported-data-symbol-pair",
        ),
        (
            "no-name-magic-validation-failed",
            "blocked-data-symbol-no-name-magic-validation-failed",
        ),
        (
            "ambiguous-sdata2-value",
            "blocked-data-symbol-ambiguous-sdata2-value",
        ),
        (
            "sdata2-pool-order-dependent",
            "blocked-data-symbol-sdata2-pool-order-dependent",
        ),
    ],
)
def test_data_symbol_name_magic_preflight_rebuckets_zero_probe_blockers(
    tmp_path: Path,
    blocker: str,
    expected_actionability: str,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_data_symbol_report(report, ["blocked_fn"])

    def name_magic_preflight(_candidate):
        return {
            "blocker": blocker,
            "stop_condition": {
                "kind": "blocked",
                "blocker": blocker,
                "reason": f"{blocker} has no source lever",
            },
            "probe_count": 0,
            "probes": [],
        }

    generate_inventory(
        report,
        output,
        checkdiff_runner=data_symbol_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        name_magic_preflight_runner=name_magic_preflight,
        workers=1,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert records[0]["source_actionability"] == expected_actionability
    assert records[0]["name_magic_blocker"] == blocker
    subqueue = output / "queues" / f"data-symbol-relocation.{blocker}.tsv"
    assert subqueue.exists()
    assert "blocked_fn" in subqueue.read_text(encoding="utf-8")


def test_data_symbol_blocker_subqueues_are_rewritten_empty(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_data_symbol_report(report, ["data_fn"])

    generate_inventory(
        report,
        output,
        checkdiff_runner=data_symbol_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        name_magic_preflight_runner=lambda _candidate: {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "blocked",
                "blocker": "no-name-magic-candidate",
                "reason": "no source-addressable relocation pair",
            },
            "probe_count": 0,
            "probes": [],
        },
        workers=1,
    )

    subqueue = output / "queues" / "data-symbol-relocation.no-name-magic-candidate.tsv"
    assert "data_fn" in subqueue.read_text(encoding="utf-8")

    generate_inventory(
        report,
        output,
        checkdiff_runner=data_symbol_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        name_magic_preflight_runner=lambda _candidate: {
            "blocker": "no-name-magic-candidate",
            "stop_condition": {
                "kind": "unvalidated",
                "blocker": "no-name-magic-candidate",
                "reason": "safe name-magic probes were generated but not compiled",
            },
            "probe_count": 1,
            "probes": [{"label": "data-symbol-static-to-global-0"}],
        },
        workers=1,
    )

    rewritten = subqueue.read_text(encoding="utf-8")
    assert "name_magic_blocker" in rewritten.splitlines()[0]
    assert "data_fn" not in rewritten


def test_data_symbol_name_magic_preflight_failure_does_not_rebucket(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    write_data_symbol_report(report, ["data_fn"])

    def failing_preflight(_candidate):
        raise RuntimeError("preflight unavailable")

    generate_inventory(
        report,
        output,
        checkdiff_runner=data_symbol_checkdiff,
        decl_order_evaluator=None,
        frame_report_runner=None,
        name_magic_preflight_runner=failing_preflight,
        workers=1,
    )

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert records[0]["source_actionability"] == "current-tools-data-symbol"
    assert records[0].get("name_magic_blocker") is None


def test_generate_inventory_attaches_stack_frame_evidence_fields(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/frame_demo",
                        "metadata": {
                            "source_path": "src/melee/demo/frame_demo.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "pure_frame_fn",
                                "size": "160",
                                "fuzzy_match_percent": 99.8,
                                "metadata": {"virtual_address": "2147485000"},
                            },
                            {
                                "name": "same_slot_fn",
                                "size": "168",
                                "fuzzy_match_percent": 99.7,
                                "metadata": {"virtual_address": "2147485100"},
                            },
                            {
                                "name": "low_spill_fn",
                                "size": "172",
                                "fuzzy_match_percent": 99.6,
                                "metadata": {"virtual_address": "2147485200"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str):
        payloads = {
            "pure_frame_fn": {
                "function": function,
                "classification": {
                    "primary": "stack-layout",
                    "stack_frame_delta": {"missing_stack_bytes": 16},
                    "reasons": ["frame reservation gap is too small"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            },
                "same_slot_fn": {
                    "function": function,
                    "classification": {
                        "primary": "stack-slot-layout",
                        "stack_slot_localizer": {
                            "frame_size": 64,
                            "mismatch_count": 1,
                            "deltas": [4],
                        },
                        "reasons": ["2 differing paired lines reference stack slots"],
                    },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            },
            "low_spill_fn": {
                "function": function,
                "classification": {
                    "primary": "stack-slot-layout",
                    "stack_slot_localizer": {
                        "deltas": [12],
                        "reserved_low_spill_region": {
                            "kind": "reserved-unused-low-spill-region",
                            "closability_tier": "ceiling",
                            "diagnostic": {
                                "frame_closability_tier": "legacy-only",
                                "preserved_raw_marker": "keep-me",
                            },
                        },
                    },
                    "reasons": ["reserved-but-unused low spill region candidate"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            },
        }
        return 1, json.dumps(payloads[function]), ""

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=None,
        workers=1,
    )

    assert result.classified_count == 3
    records = {row["function"]: row for row in read_jsonl(output / "taxonomy.records.jsonl")}

    pure = records["pure_frame_fn"]
    assert pure["frame_cause"] == "pure-reservation"
    assert pure["frame_evidence"] == "checkdiff-only"
    assert pure["frame_probe_status"] == "needs-attribution"
    assert pure["frame_match_relevance"] == "unknown"
    assert pure["frame_verdict"] == "source-reachable-candidate"
    assert pure["frame_attribution_status"] == "checkdiff-only"
    assert pure["next_command"] == pure["frame_next_command"]
    assert "debug dump local" in pure["next_command"]
    assert pure["source_actionability"] == "diagnostic-only"

    same_slot = records["same_slot_fn"]
    assert same_slot["frame_cause"] == "stack-object-offset-shift"
    assert same_slot["frame_evidence"] == "checkdiff-only"
    assert same_slot["frame_probe_status"] == "needs-attribution"
    assert same_slot["frame_match_relevance"] == "match-neutral"
    assert same_slot["source_actionability"] == "diagnostic-only"

    low_spill = records["low_spill_fn"]
    assert low_spill["frame_cause"] == "reserved-unused-low-spill-region"
    assert low_spill["frame_evidence"] == "checkdiff-only"
    assert low_spill["frame_probe_status"] == "needs-attribution"
    assert low_spill["frame_raw_cause"] == "reserved-unused-low-spill-region"
    assert low_spill["source_actionability"] == "diagnostic-only"
    assert (
        low_spill["classification"]["stack_slot_localizer"]
        ["reserved_low_spill_region"]["diagnostic"]["preserved_raw_marker"]
        == "keep-me"
    )
    assert_no_deprecated_frame_keys(records)
    assert all("frame_closability_tier" not in row for row in records.values())
    assert "#362" not in json.dumps(records)
    assert "#366" not in json.dumps(records)

    csv_text = (output / "taxonomy.records.csv").read_text(encoding="utf-8")
    assert "frame_evidence" in csv_text.splitlines()[0]
    assert "frame_probe_status" in csv_text.splitlines()[0]
    assert "frame_closability_tier" not in csv_text.splitlines()[0]
    assert "frame_match_relevance" in csv_text.splitlines()[0]
    assert "frame_match_relevance_reason" in csv_text.splitlines()[0]
    assert "frame_source_object_symbol" in csv_text.splitlines()[0]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    assert "frame_match_relevance" in stack_queue.splitlines()[0]
    assert "frame_match_relevance_reason" in stack_queue.splitlines()[0]
    header = stack_queue.splitlines()[0]
    assert "frame_cause" in header
    assert "frame_verdict" in header
    assert "frame_evidence" in header
    assert "frame_probe_status" in header
    assert "frame_closability_tier" not in header
    assert "frame_next_command" in header
    assert "cast_medium_plus_count" in header


def test_generate_inventory_uses_frame_report_source_attribution(
    tmp_path: Path,
) -> None:
    from tools.function_taxonomy_inventory import generate_inventory

    report = tmp_path / "report.json"
    output = tmp_path / "taxonomy"
    report.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/demo/attributed",
                        "metadata": {
                            "source_path": "src/melee/demo/attributed.c",
                            "complete": False,
                        },
                        "functions": [
                            {
                                "name": "attributed_fn",
                                "size": "160",
                                "fuzzy_match_percent": 99.8,
                                "metadata": {"virtual_address": "2147486000"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def runner(function: str):
        return 1, json.dumps(
            {
                "function": function,
                "classification": {
                    "primary": "stack-layout",
                    "reasons": ["frame reservation gap needs attribution"],
                },
                "structural": {"opcode_similarity": 1.0, "line_delta": 0},
            }
        ), ""

    def frame_report_runner(candidate):
        assert candidate.function == "attributed_fn"
        return {
            "function": "attributed_fn",
            "frame_first_divergence": {
                "status": "diverged",
                "cause_hypothesis": {
                    "kind": "lifetime-or-ordering-shift",
                    "source_object_symbol": "local_temp",
                },
                "source_attribution": {
                    "status": "source-object-attributed",
                    "primary_source_object": {
                        "symbol": "local_temp",
                        "current_offset": 24,
                        "expected_offset": 28,
                    },
                },
                "verdict": {
                    "status": "source-reachable-candidate",
                    "source_object_symbol": "local_temp",
                },
            },
        }

    result = generate_inventory(
        report,
        output,
        checkdiff_runner=runner,
        decl_order_evaluator=None,
        frame_report_runner=frame_report_runner,
        workers=1,
    )

    assert result.classified_count == 1
    [record] = read_jsonl(output / "taxonomy.records.jsonl")
    assert record["frame_cause"] == "lifetime-or-ordering-shift"
    assert record["frame_raw_cause"] == "lifetime-or-ordering-shift"
    assert record["frame_verdict"] == "source-reachable-candidate"
    assert record["frame_attribution_status"] == "source-object-attributed"
    assert record["frame_source_object_symbol"] == "local_temp"
    assert record["frame_source_object"]["current_offset"] == 24
    assert record["frame_evidence"] == "pcdump-attributed"
    assert record["frame_probe_status"] == "needs-attribution"
    assert "frame_closability_tier" not in record


def test_summarize_decl_order_payload_records_best_delta_and_ordering() -> None:
    from tools.function_taxonomy_inventory import summarize_decl_order_payload

    summary = summarize_decl_order_payload(
        {
            "baseline_pct": 99.1,
            "best_pct": 99.3,
            "scope": "demo_fn",
            "rounds": [
                {
                    "results": [
                        {"label": "swap a <-> b", "match_pct": 99.2, "delta": 0.1},
                        {"label": "swap b <-> c", "match_pct": 99.3, "delta": 0.2},
                    ]
                }
            ],
        }
    )

    assert summary["evaluated_status"] == "evaluated"
    assert summary["candidate_count"] == 2
    assert summary["evaluated_candidate_count"] == 2
    assert summary["best_decl_delta"] == 0.2
    assert summary["best_ordering"] == "swap b <-> c"


def test_summarize_decl_order_payload_records_dependency_stop_condition() -> None:
    from tools.function_taxonomy_inventory import summarize_decl_order_payload

    summary = summarize_decl_order_payload(
        {
            "rounds": [
                {
                    "results": [
                        {
                            "label": "swap ip <-> attr",
                            "match_pct": None,
                            "delta": None,
                            "skipped": True,
                            "skip_reason": "attr depends on ip",
                        }
                    ]
                }
            ],
        }
    )

    assert summary["evaluated_status"] == "no-freedom-init-dependency"
    assert summary["candidate_count"] == 1
    assert summary["evaluated_candidate_count"] == 0
    assert summary["skipped_count"] == 1
    assert summary["best_decl_delta"] is None
    assert summary["best_ordering"] == ""
