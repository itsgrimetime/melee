"""Tests for copy-lifetime diagnostics."""

from __future__ import annotations

import pathlib
import subprocess
import textwrap

from src.mwcc_debug.copy_trace import (
    find_virtual_to_ig,
    list_copy_lifetimes,
    trace_copy_lifetime,
)


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
        ["python", "-m", "src.cli", "debug", "virtual-to-ig", "--help"],
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


def test_trace_copy_help_exposes_copy_lifetime_command() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "trace-copy", "--help"],
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
    assert "copy" in proc.stdout.lower()


def test_pcdump_local_help_exposes_no_cache_sync() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "pcdump-local", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--no-cache-sync" in proc.stdout
