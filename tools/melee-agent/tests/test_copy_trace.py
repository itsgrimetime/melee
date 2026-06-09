"""Tests for copy-lifetime diagnostics."""

from __future__ import annotations

import pathlib
import subprocess
import textwrap

import pytest
import typer

from src.cli import debug as debug_cli
from src.mwcc_debug.copy_trace import (
    find_virtual_to_ig,
    list_copy_lifetimes,
    trace_copy_lifetime,
)
from src.mwcc_debug import copy_trace


CLI_CWD = pathlib.Path(__file__).parent.parent


PCDUMP_WITH_COPY = textwrap.dedent("""\
    Starting function fn_80247510
    BEFORE REGISTER COLORING
    fn_80247510
    B0: Succ={} Pred={} Labels={}
        mr r108,r50
        bl HSD_JObjSetMtxDirtySub
    AFTER REGISTER COLORING
    fn_80247510
    B0: Succ={} Pred={} Labels={}
        mr r30,r30
        bl HSD_JObjSetMtxDirtySub
    SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 108 1 1 0x00
        1 50 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 108 r30 1 1 0x00
          interferers: 50=r30
        1 50 r30 1 1 0x00
          interferers: 108=r30
""")


PCDUMP_AMBIGUOUS_CLASSES = textwrap.dedent("""\
    Starting function fn_80247510
    BEFORE REGISTER COLORING
    fn_80247510
    B0: Succ={} Pred={} Labels={}
        lwz r50,40(r31)
        mr r108,r50
    SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 50 1 1 0x00
        1 108 1 1 0x00
    COLORGRAPH DECISIONS (class=1, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 50 r0 1 1 0x00
        1 108 r1 1 1 0x00
    SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 50 1 1 0x00
        1 108 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 50 r31 1 1 0x00
        1 108 r30 1 1 0x00
""")


PCDUMP_COPY_REMOVED = textwrap.dedent("""\
    Starting function fn_80247510
    BEFORE GLOBAL OPTIMIZATION
    fn_80247510
    B245: Succ={} Pred={} Labels={}
        mr r108,r50
        bl HSD_JObjSetTranslateX
    AFTER PEEPHOLE FORWARD
    fn_80247510
    B245: Succ={} Pred={} Labels={}
        mr r108,r50
        bl HSD_JObjSetTranslateX
    BEFORE REGISTER COLORING
    fn_80247510
    B245: Succ={} Pred={} Labels={}
        mr r3,r50
        bl HSD_JObjSetTranslateX
    SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 50 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
      iter ig_idx phys degree nIntfr flags
        0 50 r31 1 1 0x00
""")


PCDUMP_COPY_DISCOVERY = textwrap.dedent("""\
    Starting function fn_80247510
    BEFORE REGISTER COLORING
    fn_80247510
    B244: Succ={} Pred={} Labels={}
        mr r110,r51
    B245: Succ={} Pred={} Labels={}
        mr r108,r50
    B246: Succ={} Pred={} Labels={}
        mr r64,r50
    SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
      iter ig_idx degree arraySize flags notes
        0 50 1 1 0x00
        1 51 1 1 0x00
        2 64 1 1 0x00
        3 108 1 1 0x00
        4 110 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=5)
      iter ig_idx phys degree nIntfr flags
        0 50 r31 1 1 0x00
        1 51 r29 1 1 0x00
        2 64 r28 1 1 0x00
        3 108 r30 1 1 0x00
        4 110 r27 1 1 0x00
""")


PCDUMP_CALL_RETURN_CHAIN = textwrap.dedent("""\
    Starting function fn_80000002
    BEFORE GLOBAL OPTIMIZATION
    fn_80000002
    B19: Succ={B20} Pred={} Labels={}
        bl helper_fn
    B20: Succ={B33} Pred={B19} Labels={}
        mr r59,r3
        mr r43,r59
        mr r40,r43
        cmpi cr0,r40,0
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
      iter ig_idx phys degree nIntfr flags
        0 59 r0 0 0 0x00
        1 43 r0 0 0 0x00
        2 40 r0 0 0 0x00
""")


SOURCE_CALL_RETURN_CHAIN = textwrap.dedent("""\
    void fn_80000002(void* entity) {
        int result;
        result = helper_fn(entity);
        if (result == 0) {
            sink();
        }
    }
""")


def test_find_virtual_to_ig_reports_colorgraph_identity() -> None:
    result = find_virtual_to_ig(PCDUMP_WITH_COPY, "fn_80247510", 108)

    assert result.found is True
    assert result.status == "colorgraph"
    assert result.virtual == 108
    assert result.class_id == 0
    assert result.ig_idx == 108
    assert result.simplify_iter == 0
    assert result.color_iter == 0
    assert result.assigned_reg == 30
    assert result.live_range == (0, 0)
    assert result.first_occurrence is not None
    assert result.first_occurrence.pass_name == "BEFORE REGISTER COLORING"


def test_find_virtual_to_ig_accepts_register_class() -> None:
    result = find_virtual_to_ig(
        PCDUMP_AMBIGUOUS_CLASSES,
        "fn_80247510",
        50,
        reg_class="gpr",
    )

    assert result.status == "colorgraph"
    assert result.class_id == 0
    assert result.assigned_reg == 31
    assert result.candidate_class_ids == (0, 1)
    assert result.note is not None
    assert "multiple register classes" in result.note


def test_virtual_to_ig_help_exposes_copy_debug_command() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "inspect", "virtual-to-ig",
            "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--function" in proc.stdout
    assert "--class" in proc.stdout
    assert "--json" in proc.stdout
    assert "allocator graph" in proc.stdout


def test_trace_copy_reports_allocator_coalescing() -> None:
    report = trace_copy_lifetime(
        PCDUMP_WITH_COPY,
        "fn_80247510",
        from_virtual=50,
        to_virtual=108,
    )

    assert report.status == "copy-found"
    assert report.first_copy is not None
    assert report.first_copy.pass_name == "BEFORE REGISTER COLORING"
    assert report.last_copy is not None
    assert report.to_mapping.status == "colorgraph"
    assert report.from_mapping.status == "colorgraph"
    assert report.to_mapping.assigned_reg == report.from_mapping.assigned_reg
    assert report.likely_cause == "coalesced-in-coloring"


def test_trace_copy_maps_call_return_origin_through_copy_chain() -> None:
    report = trace_copy_lifetime(
        PCDUMP_CALL_RETURN_CHAIN,
        "fn_80000002",
        from_virtual=43,
        to_virtual=40,
        source_text=SOURCE_CALL_RETURN_CHAIN,
        source_file="sample.c",
    )

    origin = report.to_mapping.call_return_origin
    assert origin is not None
    assert origin.call_symbol == "helper_fn"
    assert origin.expression == "helper_fn(entity)"
    assert origin.assigned_local == "result"
    assert origin.source_file == "sample.c"
    assert origin.source_line == 3
    assert origin.copy_chain == (40, 43, 59, 3)
    assert origin.call_site.opcode == "bl"
    assert [site.opcode for site in origin.use_sites] == ["cmpi"]


def test_trace_copy_defaults_to_gpr_class_for_r_copies() -> None:
    report = trace_copy_lifetime(
        PCDUMP_AMBIGUOUS_CLASSES,
        "fn_80247510",
        from_virtual=50,
        to_virtual=108,
    )

    assert report.from_mapping.class_id == 0
    assert report.from_mapping.assigned_reg == 31
    assert report.to_mapping.class_id == 0
    assert report.to_mapping.assigned_reg == 30


def test_trace_copy_reports_first_absent_pass_and_transform_category() -> None:
    report = trace_copy_lifetime(
        PCDUMP_COPY_REMOVED,
        "fn_80247510",
        from_virtual=50,
        to_virtual=108,
    )

    assert report.status == "copy-found"
    assert report.last_copy is not None
    assert report.last_copy.pass_name == "AFTER PEEPHOLE FORWARD"
    assert report.first_absent_pass == "BEFORE REGISTER COLORING"
    assert report.likely_cause == "removed-before-coloring"
    assert report.transform_category == "copy-propagation-or-dead-copy"


def test_list_copy_lifetimes_discovers_copies_by_virtual_and_block() -> None:
    reports = list_copy_lifetimes(
        PCDUMP_COPY_DISCOVERY,
        "fn_80247510",
        involving=50,
        near_block=245,
    )

    assert [(r.to_virtual, r.from_virtual) for r in reports] == [(108, 50)]
    assert reports[0].first_copy is not None
    assert reports[0].first_copy.block_idx == 245


def test_list_new_copy_lifetimes_reports_candidate_only_copies() -> None:
    assert hasattr(copy_trace, "list_new_copy_lifetimes")
    baseline = textwrap.dedent("""\
        Starting function fn_80247510
        BEFORE REGISTER COLORING
        fn_80247510
        B245: Succ={} Pred={} Labels={}
            bl HSD_JObjSetTranslateX
        SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
          iter ig_idx degree arraySize flags notes
            0 50 1 1 0x00
        COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
          iter ig_idx phys degree nIntfr flags
            0 50 r31 1 0 0x00
    """)

    reports = copy_trace.list_new_copy_lifetimes(
        baseline,
        PCDUMP_COPY_REMOVED,
        "fn_80247510",
        reg_class="gpr",
    )

    assert [(report.to_virtual, report.from_virtual) for report in reports] == [
        (108, 50)
    ]
    assert reports[0].likely_cause == "removed-before-coloring"


def test_trace_copy_help_exposes_copy_lifetime_command() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "inspect", "trace-copy", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--from" in proc.stdout
    assert "--to" in proc.stdout
    assert "--class" in proc.stdout
    assert "--list-copies" in proc.stdout
    assert "--involving" in proc.stdout
    assert "--near-block" in proc.stdout
    assert "--source-file" in proc.stdout
    assert "copy" in proc.stdout.lower()


def test_pcdump_local_help_exposes_no_cache_sync() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "dump", "local", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--no-cache-sync" in proc.stdout
    assert "--checkdiff-timeout" in proc.stdout


def test_pcdump_local_watchdog_exit_is_nonzero() -> None:
    assert hasattr(debug_cli, "_raise_pcdump_local_watchdog_exit")
    with pytest.raises(typer.Exit) as exc_info:
        debug_cli._raise_pcdump_local_watchdog_exit(True)

    assert exc_info.value.exit_code == 124


def test_pcdump_local_missing_build_ninja_prints_actionable_fix(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)

    with pytest.raises(typer.Exit) as exc_info:
        debug_cli._ninja_cflags_for_unit("src/melee/mn/mnvibration.c")

    captured = capsys.readouterr()
    assert exc_info.value.exit_code == 2
    assert "build.ninja missing" in captured.err
    assert "python configure.py" in captured.err


def test_pcdump_local_diff_hint_suggests_function_for_inferred_inline() -> None:
    hint = debug_cli._pcdump_local_missing_diff_target_hint(
        "mnVibration_JObjGetTranslationX",
        src_rel="src/melee/mn/mnvibration.c",
        explicit=False,
    )

    assert "mnVibration_JObjGetTranslationX" in hint
    assert "first function" in hint
    assert "static inline" in hint
    assert "--function" in hint
