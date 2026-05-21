"""Tests for copy-lifetime diagnostics."""

from __future__ import annotations

import pathlib
import subprocess
import textwrap

from src.mwcc_debug.copy_trace import find_virtual_to_ig, trace_copy_lifetime


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
    assert "copy" in proc.stdout.lower()
