"""Tests for scheduler source-shape suggestions."""
from __future__ import annotations

from src.mwcc_debug.suggest_schedule import render_text, run


def _pcdump_with_pre_and_final(pre_body: str, final_body: str) -> str:
    return (
        "Starting function fn_80000000\n"
        "AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        f"{pre_body}"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        f"{final_body}"
    )


def test_suggest_schedule_ranks_mechanical_source_reshapes() -> None:
    source = (
        "typedef struct Obj Obj;\n"
        "extern Obj* pl_804D6470;\n"
        "void fn_80000000(void) {\n"
        "    sink(pl_804D6470->x90, pl_804D6470->x94);\n"
        "}\n"
    )
    real = _pcdump_with_pre_and_final(
        "    lwz     r40,148(r32)\n"
        "    lwz     r41,144(r32)\n",
        "    lwz     r6,144(r31)\n"
        "    lwz     r7,148(r31)\n",
    )
    forced = _pcdump_with_pre_and_final(
        "    lwz     r40,148(r32)\n"
        "    lwz     r41,144(r32)\n",
        "    lwz     r7,148(r31)\n"
        "    lwz     r6,144(r31)\n",
    )

    report = run(
        real,
        forced,
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
        source_text=source,
        source_file="src/test.c",
    )

    assert report.finding is not None
    assert report.finding.rule.raw == "lwz:0x94>0x90"
    assert report.mode == "structural"
    assert report.suggestions
    first = report.suggestions[0]
    assert first.kind == "split-enclosing-statement"
    assert first.mechanically_applicable is True
    assert first.target_expression == "pl_804D6470->x94"
    assert first.observed_expression == "pl_804D6470->x90"
    assert "pl_804D6470->x94" in first.patch_hint
    assert "pl_804D6470->x90" in first.patch_hint
    assert "priority data unavailable" in report.caveat

    text = render_text(report)
    assert "suggest-schedule-source - fn_80000000" in text
    assert "mode: structural" in text
    assert "rule=lwz:0x94>0x90" in text
    assert "expr=pl_804D6470->x94" in text
    assert "split-enclosing-statement" in text
    assert "priority data unavailable" in text
