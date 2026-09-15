from pathlib import Path

import json

from src.inline_leverage.run import (
    make_real_tree_scorer,
    measure_function_source,
    summarize_records,
)
from src.inline_leverage.types import ScoreResult


SOURCE = """
static inline f32 framef(HSD_JObj* jobj) {
    return mn_frame(jobj);
}

void target(HSD_JObj* jobj) {
    f32 y = framef(jobj);
}
"""

SCALAR_MULTI_SOURCE = """
static inline int sum_name_kos(u8 field_index) {
    int total;
    int j;
    total = 0;
    for (j = total; j < 0x78; j++) {
        if (GetNameText(j & 0xFF)) {
            total += GetPersistentNameData(field_index)->vs_kos[(u8) j];
        }
    }
    return total;
}

void target(u32* tp, int n) {
    *tp = sum_name_kos(n & 0xFF);
}
"""


def test_measure_function_source_uses_injected_scorer() -> None:
    def scorer(_patched_source: str, _inline_name: str) -> ScoreResult:
        return ScoreResult(
            compiled=True,
            baseline_pct=100.0,
            deinlined_pct=99.6,
            delta_fuzzy=0.4,
            baseline_ndl=0,
            deinlined_ndl=2,
            delta_struct=2,
        )

    records = measure_function_source(
        source=SOURCE,
        function="target",
        unit="u.c",
        run_id="test-run",
        scorer=scorer,
    )

    assert len(records) == 1
    assert records[0].inline_name == "framef"
    assert records[0].verdict == "lever"
    assert records[0].delta_struct == 2


def test_summarize_records_reports_bucket_counts() -> None:
    records = measure_function_source(
        source=SOURCE,
        function="target",
        unit="u.c",
        run_id="test-run",
        scorer=lambda _source, _name: ScoreResult(
            compiled=True,
            baseline_pct=100.0,
            deinlined_pct=100.0,
            delta_fuzzy=0.0,
            baseline_ndl=0,
            deinlined_ndl=0,
            delta_struct=0,
        ),
    )

    summary = summarize_records(records)

    assert summary["total_pairs"] == 1
    assert summary["buckets"]["neutral"] == 1
    assert summary["shape_buckets"]


def test_measure_function_source_dry_run_keeps_evidence() -> None:
    records = measure_function_source(
        source=SOURCE,
        function="target",
        unit=str(Path("u.c")),
        run_id="test-run",
        scorer=None,
    )

    assert records[0].verdict == "unsupported"
    assert records[0].error == "dry-run: scoring disabled"
    assert records[0].shape_args == ["plain_id"]


def test_measure_function_source_scores_scalar_multi_statement_assignment() -> None:
    def scorer(patched_source: str, _inline_name: str) -> ScoreResult:
        assert "GetPersistentNameData(n & 0xFF)" in patched_source
        assert "*tp = total;" in patched_source
        return ScoreResult(
            compiled=True,
            baseline_pct=100.0,
            deinlined_pct=99.6,
            delta_fuzzy=0.4,
            baseline_ndl=0,
            deinlined_ndl=2,
            delta_struct=2,
        )

    records = measure_function_source(
        source=SCALAR_MULTI_SOURCE,
        function="target",
        unit="u.c",
        run_id="test-run",
        scorer=scorer,
    )

    assert len(records) == 1
    assert records[0].inline_name == "sum_name_kos"
    assert records[0].verdict == "lever"
    assert records[0].expansion_form == "scalar_assignment_splice"
    assert records[0].shape_return == "scalar"
    assert records[0].shape_body == "multi_statement"
    assert records[0].shape_args == ["expression"]


def test_measure_function_source_dry_run_retains_scalar_assignment_form() -> None:
    records = measure_function_source(
        source=SCALAR_MULTI_SOURCE,
        function="target",
        unit="u.c",
        run_id="test-run",
        scorer=None,
    )

    assert len(records) == 1
    assert records[0].verdict == "unsupported"
    assert records[0].error == "dry-run: scoring disabled"
    assert records[0].expansion_form == "scalar_assignment_splice"


def test_real_tree_scorer_writes_evidence(monkeypatch, tmp_path) -> None:
    root = tmp_path
    source_path = root / "unit.c"
    source_path.write_text(SCALAR_MULTI_SOURCE)
    payloads = [
        {
            "fuzzy_match_percent": 100.0,
            "classification": {
                "structural_truth_gate": {"normalized_diff_lines": 0}
            },
        },
        {
            "fuzzy_match_percent": 99.0,
            "classification": {
                "structural_truth_gate": {"normalized_diff_lines": 3}
            },
        },
    ]

    def fake_checkdiff(_root, _function, _timeout):
        return payloads.pop(0)

    monkeypatch.setattr("src.inline_leverage.run._run_checkdiff", fake_checkdiff)
    scorer = make_real_tree_scorer(
        melee_root=root,
        source_path=source_path,
        function="target",
        timeout=1.0,
        evidence_dir=root / "evidence",
    )

    records = measure_function_source(
        source=SCALAR_MULTI_SOURCE,
        function="target",
        unit="unit.c",
        run_id="test-run",
        scorer=scorer,
    )

    assert records[0].verdict == "lever"
    assert records[0].evidence is not None
    evidence = records[0].evidence
    for key in (
        "baseline_source",
        "deinlined_source",
        "baseline_checkdiff",
        "deinlined_checkdiff",
        "score",
        "pcdump_blocker",
    ):
        assert Path(evidence[key]).is_file()
    assert "sum_name_kos(n & 0xFF)" in Path(evidence["baseline_source"]).read_text()
    assert "*tp = total;" in Path(evidence["deinlined_source"]).read_text()
    assert json.loads(Path(evidence["score"]).read_text())["delta_struct"] == 3
    assert (
        json.loads(Path(evidence["pcdump_blocker"]).read_text())["status"]
        == "not_collected"
    )
