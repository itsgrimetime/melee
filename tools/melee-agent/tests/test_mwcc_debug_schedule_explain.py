"""Tests for scheduler decision explanation helpers."""
from __future__ import annotations

from src.mwcc_debug.schedule_explain import (
    diff_schedule,
    explain_schedule,
    render_diff_text,
    render_text,
)


def _pcdump_for(body: str) -> str:
    return (
        "Starting function fn_80000000\n"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        f"{body}"
    )


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


def test_explain_schedule_records_adjacent_loads_without_priority_data() -> None:
    report = explain_schedule(
        _pcdump_for(
            "    lwz     r6,144(r31)\n"
            "    lwz     r7,148(r31)\n"
        ),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
    )

    assert report.function == "fn_80000000"
    assert report.decisions[0].status == "matched"
    assert report.decisions[0].heuristic_verdict == "PRIORITY_UNAVAILABLE"
    assert report.decisions[0].window_gap == 0
    assert report.decisions[0].candidates[0].window_rank == 0
    assert report.decisions[0].candidates[1].window_rank == 0
    assert "adjacent same-base loads" in report.decisions[0].rationale
    assert "priority data unavailable" in report.decisions[0].rationale


def test_explain_schedule_records_straddled_load_window_gap() -> None:
    report = explain_schedule(
        _pcdump_for(
            "    lwz     r6,144(r31)\n"
            "    addi    r9,r31,8\n"
            "    lwz     r7,148(r31)\n"
        ),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
    )

    decision = report.decisions[0]
    assert decision.status == "matched"
    assert decision.heuristic_verdict == "PRIORITY_UNAVAILABLE"
    assert decision.window_gap == 1
    assert "intervening instruction" in decision.rationale
    assert "priority data unavailable" in decision.rationale


def test_explain_schedule_records_already_target_straddled_window_gap() -> None:
    report = explain_schedule(
        _pcdump_for(
            "    lwz     r7,148(r31)\n"
            "    addi    r9,r31,8\n"
            "    lwz     r6,144(r31)\n"
        ),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
    )

    decision = report.decisions[0]
    assert decision.status == "already-target"
    assert decision.heuristic_verdict == "PRIORITY_UNAVAILABLE"
    assert decision.window_gap == 1
    assert [cand.role for cand in decision.candidates] == [
        "target-first",
        "intervening",
        "target-second",
    ]
    assert "target order is already present" in decision.rationale
    assert "priority data unavailable" in decision.rationale


def test_render_text_labels_window_rank_and_unavailable_priority_data() -> None:
    report = explain_schedule(
        _pcdump_for(
            "    lwz     r6,144(r31)\n"
            "    lwz     r7,148(r31)\n"
        ),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
    )

    out = render_text(report)

    assert "explain-schedule - fn_80000000" in out
    assert "lwz:0x94>0x90" in out
    assert "heuristic_verdict=PRIORITY_UNAVAILABLE" in out
    assert "window_gap=0" in out
    assert "window_rank=0" in out
    assert "priority data unavailable" in out
    assert "small source-order nudges" not in out
    assert "priority=" not in out
    assert "heuristic_rank=" not in out


def test_explain_schedule_attaches_source_provenance_to_load_candidates() -> None:
    source = (
        "typedef struct Obj Obj;\n"
        "void fn_80000000(Obj* obj) {\n"
        "    int hi = obj->x94;\n"
        "    int lo = obj->x90;\n"
        "    sink(hi, lo);\n"
        "}\n"
    )
    report = explain_schedule(
        _pcdump_with_pre_and_final(
            "    lwz     r40,148(r32)\n"
            "    lwz     r41,144(r32)\n",
            "    lwz     r7,148(r31)\n"
            "    lwz     r6,144(r31)\n",
        ),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
        source_text=source,
        source_file="src/test.c",
    )

    first = report.decisions[0].candidates[0].source
    second = report.decisions[0].candidates[1].source
    assert first is not None
    assert first.ir_node_id == "B0:0"
    assert first.ir_virtual == 40
    assert first.base_virtual == 32
    assert first.base_var == "obj"
    assert first.field_offset == 0x94
    assert first.field_name == "x94"
    assert first.expression == "obj->x94"
    assert first.source_file == "src/test.c"
    assert first.source_line == 3
    assert first.source_col == 13
    assert first.confidence == "source-expression"
    assert second is not None
    assert second.expression == "obj->x90"

    out = render_text(report)
    assert "ir=B0:0" in out
    assert "source=src/test.c:3:13" in out
    assert "expr=obj->x94" in out


def test_explain_schedule_finds_global_field_source_without_base_binding() -> None:
    source = (
        "typedef struct Obj Obj;\n"
        "extern Obj* pl_804D6470;\n"
        "void fn_80000000(void) {\n"
        "    int hi = pl_804D6470->x94;\n"
        "    int lo = pl_804D6470->x90;\n"
        "    sink(hi, lo);\n"
        "}\n"
    )
    report = explain_schedule(
        _pcdump_with_pre_and_final(
            "    lwz     r40,148(r32)\n"
            "    lwz     r41,144(r32)\n",
            "    lwz     r7,148(r31)\n"
            "    lwz     r6,144(r31)\n",
        ),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
        source_text=source,
        source_file="src/test.c",
    )

    first = report.decisions[0].candidates[0].source
    second = report.decisions[0].candidates[1].source
    assert first is not None
    assert first.ir_node_id == "B0:0"
    assert first.base_virtual == 32
    assert first.base_var == "pl_804D6470"
    assert first.field_offset == 0x94
    assert first.field_name == "x94"
    assert first.expression == "pl_804D6470->x94"
    assert first.source_file == "src/test.c"
    assert first.source_line == 4
    assert first.source_col == 13
    assert first.confidence == "source-expression"
    assert second is not None
    assert second.expression == "pl_804D6470->x90"

    out = render_text(report)
    assert "source=src/test.c:4:13" in out
    assert "expr=pl_804D6470->x94" in out


def test_diff_schedule_reports_first_divergent_pick_with_source() -> None:
    source = (
        "typedef struct Obj Obj;\n"
        "void fn_80000000(Obj* obj) {\n"
        "    int hi = obj->x94;\n"
        "    int lo = obj->x90;\n"
        "    sink(hi, lo);\n"
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

    report = diff_schedule(
        real,
        forced,
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
        source_text=source,
        source_file="src/test.c",
    )

    finding = report.finding
    assert finding is not None
    assert finding.step == 1
    assert finding.rule.raw == "lwz:0x94>0x90"
    assert finding.real_status == "matched"
    assert finding.forced_status == "already-target"
    assert finding.margin is None
    assert finding.real_pick is not None
    assert finding.real_pick.offset == 0x90
    assert finding.real_pick.source is not None
    assert finding.real_pick.source.expression == "obj->x90"
    assert finding.forced_pick is not None
    assert finding.forced_pick.offset == 0x94
    assert finding.forced_pick.source is not None
    assert finding.forced_pick.source.expression == "obj->x94"

    out = render_diff_text(report)
    assert "first divergence: step=1 rule=lwz:0x94>0x90" in out
    assert "real picked observed-first" in out
    assert "forced picked target-first" in out
    assert "margin=priority data unavailable" in out
    assert "expr=obj->x94" in out
