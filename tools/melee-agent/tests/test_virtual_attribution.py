"""Tests for virtual-register source/interference attribution."""

from __future__ import annotations

import json
import pathlib
import subprocess
import textwrap

from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.virtual_attribution import explain_virtuals

CLI_CWD = pathlib.Path(__file__).parent.parent
runner = CliRunner()


PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    AFTER INSTRUCTION SELECTION
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r50,r3
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
        stw r40,16(r32)
    B1: Succ={} Pred={} Labels={}
        lwz r43,24(r32)
        add r44,r43,r33
    AFTER REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r31,12(r3)
        add r30,r31,r4
        stw r30,16(r3)
    B1: Succ={} Pred={} Labels={}
        lwz r29,24(r3)
        add r28,r29,r4
    SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 33 2 2 0x00
        1 37 1 1 0x00
        2 40 1 1 0x00
        3 43 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=4)
      iter ig_idx phys degree nIntfr flags
        0 33 r4 2 2 0x00
          interferers: 43=r29
        1 37 r31 1 1 0x00
          interferers: 40=r30
        2 40 r30 1 1 0x00
          interferers: 37=r31
        3 43 r29 1 1 0x00
          interferers: 33=r4
""")


SOURCE = textwrap.dedent("""\
    typedef struct Obj {
        int xC;
        int x10;
        int x18;
    } Obj;

    void fn_80000000(Obj* obj, int extra) {
        int temp;
        temp = obj->xC + extra;
        obj->x10 = temp;
        sink(obj->x18 + extra);
    }
""")


def test_explain_virtuals_attaches_source_and_interference() -> None:
    report = explain_virtuals(
        PCDUMP,
        "fn_80000000",
        virtuals=[37, 40, 43, 33],
        pairs=[(37, 40), (43, 33)],
        source_text=SOURCE,
        source_file="sample.c",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    assert by_virtual[37].source is not None
    assert by_virtual[37].source.expression == "obj->xC"
    assert by_virtual[37].source.source_line == 9
    assert by_virtual[37].source.base_virtual == 32
    assert by_virtual[37].live_blocks == (0,)
    assert by_virtual[37].assigned_reg == 31
    assert by_virtual[37].last_occurrence is not None
    assert by_virtual[37].last_occurrence.pass_name == "BEFORE REGISTER COLORING"

    assert by_virtual[33].source is not None
    assert by_virtual[33].source.name == "extra"
    assert by_virtual[33].source.kind == "param"

    first = report.pair_interferences[0]
    assert first.virtual == 37
    assert first.other_virtual == 40
    assert first.colorgraph_interference is True
    assert first.live_overlap is True
    assert "cannot coalesce" in first.reason
    assert "live ranges overlap" in first.reason

    second = report.pair_interferences[1]
    assert second.virtual == 43
    assert second.other_virtual == 33
    assert second.colorgraph_interference is True
    assert second.live_overlap is True


def test_explain_virtuals_ignores_colorgraph_interferer_rows_as_occurrences() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000001
        BEFORE REGISTER COLORING
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            mr r37,r33
        AFTER PEEPHOLE FORWARD
        fn_80000001
        B0: Succ={} Pred={} Labels={}
            mr r37,r33
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
          iter ig_idx phys degree nIntfr flags
            0 45 r40 1 1 0x00
              interferers: 40=r6 45=r40 120=r-1 121=r-1
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000001",
        virtuals=[40, 45],
        source_text="void fn_80000001(void) {}\n",
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    entry = by_virtual[40]
    assert entry.status == "not-found"
    assert entry.live_range is None
    assert entry.use_count == 0
    assert entry.first_occurrence is None
    assert entry.last_occurrence is None
    assert entry.source is None
    assert entry.note is not None
    assert "not found in parsed pcode passes" in entry.note

    colorgraph_only = by_virtual[45]
    assert colorgraph_only.status == "colorgraph"
    assert colorgraph_only.first_occurrence is None
    assert colorgraph_only.last_occurrence is None
    assert colorgraph_only.note is not None
    assert "no real pcode occurrence" in colorgraph_only.note


def test_explain_virtuals_collapses_call_return_copy_chain_to_source() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000002
        BEFORE GLOBAL OPTIMIZATION
        fn_80000002
        B19: Succ={B20} Pred={} Labels={}
            bl helper_fn
        B20: Succ={B33} Pred={B19} Labels={}
            mr r59,r3
            mr r43,r59
            mr r40,r43
            cmpi cr0,r43,1
        B33: Succ={} Pred={B20} Labels={}
            cmpi cr0,r40,0
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
          iter ig_idx phys degree nIntfr flags
            0 59 r0 0 0 0x00
            1 43 r0 0 0 0x00
            2 40 r0 0 0 0x00
    """)
    source = textwrap.dedent("""\
        void fn_80000002(void* entity) {
            int result;
            int b34;
            result = helper_fn(entity);
            b34 = result;
            if (b34 == 0) {
                sink();
            }
        }
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000002",
        virtuals=[40],
        source_text=source,
        source_file="sample.c",
    )

    source_info = report.virtuals[0].source
    assert source_info is not None
    assert source_info.kind == "call-return"
    assert source_info.confidence == "copy-chain"
    assert source_info.name == "result"
    assert source_info.expression == "helper_fn(entity)"
    assert source_info.call_symbol == "helper_fn"
    assert source_info.copy_chain == (40, 43, 59, 3)
    assert source_info.source_file == "sample.c"
    assert source_info.source_line == 4
    assert [site.opcode for site in source_info.use_sites] == ["cmpi"]


def test_explain_virtuals_classifies_ir_first_def_provenance_without_source() -> None:
    pcdump = textwrap.dedent("""\
        Starting function fn_80000003
        BEFORE REGISTER COLORING
        fn_80000003
        B0: Succ={} Pred={} Labels={}
            add r38,r32,r33
            mr r39,r38
            lwz r44,12(r32)
        AFTER REGISTER COLORING
        fn_80000003
        B0: Succ={} Pred={} Labels={}
            add r6,r3,r4
            mr r7,r6
            lwz r8,12(r3)
    """)

    report = explain_virtuals(
        pcdump,
        "fn_80000003",
        virtuals=[38, 39, 44],
    )

    by_virtual = {entry.virtual: entry for entry in report.virtuals}
    assert by_virtual[38].source is not None
    assert by_virtual[38].source.kind == "implicit-temp"
    assert by_virtual[38].source.confidence == "pcode-first-def"
    assert by_virtual[38].source.expression == "add r38,r32,r33"

    assert by_virtual[39].source is not None
    assert by_virtual[39].source.kind == "copy/coalesce-product"
    assert by_virtual[39].source.base_virtual == 38
    assert by_virtual[39].source.expression == "mr r39,r38"

    assert by_virtual[44].source is not None
    assert by_virtual[44].source.kind == "load/store-address"
    assert by_virtual[44].source.base_virtual == 32
    assert by_virtual[44].source.field_offset == 12


def test_explain_virtual_cli_all_reports_every_pcode_virtual(tmp_path: pathlib.Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    source = tmp_path / "sample.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-virtual",
            "-f",
            "fn_80000000",
            "--all",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert {entry["virtual"] for entry in payload["virtuals"]} == {
        32,
        33,
        37,
        40,
        43,
        44,
        50,
    }
    by_virtual = {entry["virtual"]: entry for entry in payload["virtuals"]}
    assert by_virtual[32]["source"]["name"] == "obj"
    assert by_virtual[33]["source"]["kind"] == "param"
    assert by_virtual[37]["source"]["expression"] == "obj->xC"
    assert by_virtual[43]["source"]["expression"] == "obj->x18"
    assert by_virtual[44]["source"]["kind"] == "implicit-temp"


def test_explain_virtual_cli_outputs_json(tmp_path: pathlib.Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    source = tmp_path / "sample.c"
    pcdump.write_text(PCDUMP)
    source.write_text(SOURCE)

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-virtual",
            "-f",
            "fn_80000000",
            "--virtuals",
            "r37,r40,r43,r33",
            "--pairs",
            "r37:r40,r43:r33",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function"] == "fn_80000000"
    assert payload["virtuals"][0]["virtual"] == 37
    assert payload["virtuals"][0]["source"]["expression"] == "obj->xC"
    assert payload["pair_interferences"][0]["colorgraph_interference"] is True
    assert "cannot coalesce" in payload["pair_interferences"][0]["reason"]


def test_explain_virtual_help_is_registered() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "inspect",
            "explain-virtual", "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--virtuals" in proc.stdout
    assert "--pairs" in proc.stdout
    assert "source/interference" in proc.stdout
