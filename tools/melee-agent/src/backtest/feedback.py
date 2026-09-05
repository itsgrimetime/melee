from __future__ import annotations

import json
from pathlib import Path


def stage_gap(case: dict, *, staging_dir: Path) -> Path:
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / f"{case['case_id']}.json"
    path.write_text(json.dumps({
        "function": case["function"],
        "lever_class": case["lever_class"],
        "ground_truth_diff": case["ground_truth_diff"],
        "suggested_action": "Review for a new mismatch-db/mining-ledger pattern (staged, not committed).",
    }, indent=2))
    return path


def issue_report_argv(case: dict) -> list:
    summary = f"backtest GAP: tooling missed {case['lever_class']} lever on {case['function']}"
    return [
        "issue", "report", summary,
        "--tool", "backtest", "--kind", "feature",
        "--function", case["function"],
        "--body", f"Lever class {case['lever_class']} not surfaced by advisory/generative tiers "
                  f"(case {case['case_id']}). Ground-truth diff staged under build/backtest/staged/.",
    ]
