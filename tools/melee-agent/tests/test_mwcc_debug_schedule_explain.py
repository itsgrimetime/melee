"""Tests for scheduler decision explanation helpers."""
from __future__ import annotations

from src.mwcc_debug.asm_windows import (
    explain_code_offset_window,
    parse_asm_lines,
)
from src.mwcc_debug.schedule_explain import (
    diff_schedule,
    explain_schedule,
    parse_schedule_rules,
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


def test_explain_schedule_records_straddled_addi_code_offset_window() -> None:
    target_asm = [
        "<it_802BCB88>:",
        "+1f8: c0 21 00 60 \tlfs     f1,96(r1)",
        "+1fc: 3b 9c 00 01 \taddi    r28,r28,1",
        "+200: c0 01 00 6c \tlfs     f0,108(r1)",
        "+204: 38 61 00 48 \taddi    r3,r1,72",
    ]
    current_asm = [
        "<it_802BCB88>:",
        "+1f8: c0 21 00 60 \tlfs     f1,96(r1)",
        "+1fc: 38 61 00 48 \taddi    r3,r1,72",
        "+200: c0 01 00 6c \tlfs     f0,108(r1)",
        "+204: 3b 9c 00 01 \taddi    r28,r28,1",
    ]
    source = (
        "void it_802BCB88(void) {\n"
        "    int count;\n"
        "    Vec3 dir;\n"
        "    count++;\n"
        "    lbVector_Normalize(&dir);\n"
        "}\n"
    )

    report = explain_schedule(
        _pcdump_for(
            "    addi    r3,r1,72\n"
            "    lfs     f0,108(r1)\n"
            "    addi    r28,r28,1\n"
        ),
        function="it_802BCB88",
        force_schedule="addi:0x204>0x1fc",
        target_asm=target_asm,
        current_asm=current_asm,
        source_text=source,
        source_file="src/melee/it/items/itseakchain.c",
    )

    decision = report.decisions[0]
    assert decision.status == "matched"
    assert decision.window_kind == "asm-code-offset"
    assert decision.window_gap == 1
    assert decision.forceability == "not-forceable-by-current-hook"
    assert decision.source_shape_verdict == "source-shape-controllable"
    assert decision.heuristic_verdict == "SOURCE_SHAPE_CONTROLLABLE"
    assert [cand.role for cand in decision.candidates] == [
        "observed-first",
        "intervening",
        "target-first",
    ]
    assert decision.candidates[0].instruction_class == (
        "local-address-materialization"
    )
    assert decision.candidates[2].instruction_class == "counter-increment"
    assert [item.kind for item in decision.source_reshapes][:2] == [
        "delay-local-address-materialization",
        "anchor-counter-increment",
    ]

    out = render_text(report)
    assert "window_kind=asm-code-offset" in out
    assert "forceability=not-forceable-by-current-hook" in out
    assert "local-address-materialization" in out
    assert "counter-increment" in out
    assert "delay-local-address-materialization" in out


def test_checkdiff_json_does_not_reinterpret_missing_load_operand_rules() -> None:
    target_asm = [
        "<fn_80000000>:",
        "+090: 80 64 00 00 \tlwz     r3,0(r4)",
        "+094: 80 a4 00 04 \tlwz     r5,4(r4)",
    ]
    current_asm = [
        "<fn_80000000>:",
        "+090: 80 a4 00 04 \tlwz     r5,4(r4)",
        "+094: 80 64 00 00 \tlwz     r3,0(r4)",
    ]

    report = explain_schedule(
        _pcdump_for("    addi    r3,r3,1\n"),
        function="fn_80000000",
        force_schedule="lwz:0x94>0x90",
        target_asm=target_asm,
        current_asm=current_asm,
    )

    decision = report.decisions[0]
    assert decision.status == "missing"
    assert decision.window_kind is None
    assert "same-base load window" in decision.rationale


def test_parse_asm_lines_ignores_relocation_records() -> None:
    instructions = parse_asm_lines([
        "+010: 3c 60 00 00 \tlis     r3,lbl_804D0000@ha",
        "        R_PPC_ADDR16_HA lbl_804D0000",
        "+014: 38 63 00 00 \taddi    r3,r3,lbl_804D0000@l",
        "        R_PPC_ADDR16_LO lbl_804D0000",
    ])

    assert [inst.opcode for inst in instructions] == ["lis", "addi"]
    assert [inst.offset for inst in instructions] == [0x10, 0x14]


def test_addi_code_offset_window_disambiguates_duplicate_target_bodies_by_order() -> None:
    rule = parse_schedule_rules("addi:0x204>0x1fc")[0]
    target_asm = [
        "<it_802BCB88>:",
        "+010: 3b 9c 00 01 \taddi    r28,r28,1",
        "+014: 38 61 00 48 \taddi    r3,r1,72",
        "+100: 3b 9c 00 01 \taddi    r28,r28,1",
        "+104: c0 01 00 6c \tlfs     f0,108(r1)",
        "+108: 38 61 00 48 \taddi    r3,r1,72",
    ]
    current_asm = [
        "<it_802BCB88>:",
        "+1fc: 38 61 00 48 \taddi    r3,r1,72",
        "+200: c0 01 00 6c \tlfs     f0,108(r1)",
        "+204: 3b 9c 00 01 \taddi    r28,r28,1",
    ]

    result = explain_code_offset_window(rule, target_asm, current_asm)

    assert result is not None
    assert result.status == "matched"
    assert [cand.role for cand in result.candidates] == [
        "observed-first",
        "intervening",
        "target-first",
    ]
    assert [cand.target_index for cand in result.candidates] == [4, 3, 2]


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
