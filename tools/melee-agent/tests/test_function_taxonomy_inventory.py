from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


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
    }
    if function == "broken_fn":
        return 1, "", "error: could not find broken_fn in compiled object"
    return 1, json.dumps(payloads[function]), "checkdiff stderr"


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
        workers=1,
    )

    assert result.report_non100_count == 3
    assert result.classified_count == 2
    assert result.error_count == 1

    records = read_jsonl(output / "taxonomy.records.jsonl")
    assert [row["function"] for row in records] == ["stack_fn", "small_fn"]
    assert records[0]["file_path"] == "melee/demo/demo.c"
    assert records[0]["address"] == "0x8000000c"
    assert records[0]["match_tier"] == ">=99%"
    assert records[0]["work_bucket"] == "stack-local-layout"
    assert records[0]["subcategory"] == "same-frame-stack-slot-placement"
    assert records[1]["known_small_pattern_candidate"] is True
    assert records[1]["work_bucket"] == "known-small-pattern-candidate"

    errors = read_jsonl(output / "checkdiff-errors.jsonl")
    assert errors[0]["function"] == "broken_fn"
    assert "could not find broken_fn" in errors[0]["message"]

    stack_queue = (output / "queues" / "stack-local-layout.tsv").read_text(
        encoding="utf-8"
    )
    assert "match_percent\tfunction\tprimary\tsubcategory\tfile_path\tnext_command" in stack_queue
    assert "99.75000\tstack_fn\tstack-slot-layout" in stack_queue

    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "| Report non-100% | 3 |" in summary
    assert "| stack-local-layout | 1 |" in summary
    assert "| known-small-pattern-candidate | 1 |" in summary


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
        workers=1,
        limit=1,
    )

    assert result.report_non100_count == 3
    assert result.attempted_count == 1
    assert seen == ["stack_fn"]
