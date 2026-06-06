# tests/test_struct_verify.py
"""Tests for struct verify Phase 3+4: functions_for_unit, aggregation, CLI command, renderer,
and end-to-end THPDec dogfood against the pre-fix layout (Task 4.1)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# Gate slow compiler-dependent tests on MWCC + wibo being present.
_COMPILER_PRESENT = (
    (REPO / "build/tools/wibo").exists()
    and (REPO / "build/compilers/GC/1.2.5/mwcceppc.exe").exists()
)
_LIVE_GUARD = pytest.mark.skipif(
    not _COMPILER_PRESENT,
    reason="MWCC not built (build/tools/wibo + build/compilers/GC/1.2.5/mwcceppc.exe)",
)


# ---------------------------------------------------------------------------
# Task 3.1: functions_for_unit helper
# ---------------------------------------------------------------------------

def test_functions_for_unit_thpdec():
    from src.extractor import report as report_mod
    fns = report_mod.functions_for_unit(REPO / "build/GALE01/report.json", "thp/THPDec")
    assert "__THPRestartDefinition" in fns
    assert "THPVideoDecode" in fns
    assert all(isinstance(f, str) for f in fns)


def test_functions_for_unit_not_found():
    from src.extractor import report as report_mod
    import pytest
    with pytest.raises(ValueError, match="not found"):
        report_mod.functions_for_unit(REPO / "build/GALE01/report.json", "nonexistent/DoesNotExist")


# ---------------------------------------------------------------------------
# Task 3.2: aggregate + confidence
# ---------------------------------------------------------------------------

def test_aggregate_keeps_singletons_and_flags_ambiguous():
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
        {"function": "f2", "field": "nMCU", "current": 0x742, "expected": 0x8fc},
        {"function": "f3", "field": "nMCU", "current": 0x742, "expected": 0x8fc},
        # ambiguous: same field, conflicting expected
        {"function": "f4", "field": "RST", "current": 0x740, "expected": 0x123},
    ]
    agg = sv.aggregate(findings)
    rst = next(a for a in agg if a["field"] == "RST")
    nmcu = next(a for a in agg if a["field"] == "nMCU")
    assert rst["conflict"] is True              # RST has two expecteds
    assert nmcu["n_functions"] == 2 and nmcu["conflict"] is False
    assert nmcu["confidence"] == "high"         # >=2 agreeing
    # agreeing functions collapse to a single expected value
    assert nmcu["expected"] == 0x8fc


def test_aggregate_singleton_confidence_low():
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
    ]
    agg = sv.aggregate(findings)
    assert len(agg) == 1
    assert agg[0]["confidence"] == "low"
    assert agg[0]["n_functions"] == 1
    assert agg[0]["conflict"] is False
    assert agg[0]["expected"] == 0x900


def test_aggregate_sorted_by_current():
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "B", "current": 0x900, "expected": 0xa00},
        {"function": "f2", "field": "A", "current": 0x100, "expected": 0x200},
    ]
    agg = sv.aggregate(findings)
    assert agg[0]["field"] == "A"
    assert agg[1]["field"] == "B"


def test_aggregate_empty():
    from src.common import struct_verify as sv
    assert sv.aggregate([]) == []


def test_aggregate_flags_ambiguous_when_ref_field_differs():
    from src.common import struct_verify as sv
    findings = [
        # ambiguous: cur_disp maps to "predDC" but ref_disp maps to a DIFFERENT
        # known field "nextField" -> could be a deliberate different-field access
        {"function": "f1", "field": "predDC", "current": 0x100, "expected": 0x110,
         "ref_field": "nextField"},
        # normal: ref_field is None -> not ambiguous
        {"function": "f2", "field": "RST", "current": 0x740, "expected": 0x900,
         "ref_field": None},
        # normal: ref_field == field (plain offset shift of the SAME field) -> not ambiguous
        {"function": "f3", "field": "nMCU", "current": 0x742, "expected": 0x8fc,
         "ref_field": "nMCU"},
    ]
    agg = sv.aggregate(findings)
    by_field = {a["field"]: a for a in agg}
    assert by_field["predDC"]["ambiguous"] is True
    assert by_field["RST"]["ambiguous"] is False
    assert by_field["nMCU"]["ambiguous"] is False


def test_aggregate_ambiguous_defaults_false_when_key_absent():
    # Findings produced before the ref_field enrichment (or for a non-mapping
    # path) must still aggregate, defaulting ambiguous to False.
    from src.common import struct_verify as sv
    findings = [
        {"function": "f1", "field": "RST", "current": 0x740, "expected": 0x900},
    ]
    agg = sv.aggregate(findings)
    assert agg[0]["ambiguous"] is False


# ---------------------------------------------------------------------------
# Task 3.3: struct verify CLI help test
# ---------------------------------------------------------------------------

def test_struct_verify_help():
    from typer.testing import CliRunner
    from src.cli.struct import struct_app
    r = CliRunner().invoke(struct_app, ["verify", "--help"])
    assert r.exit_code == 0
    assert "--struct" in r.output and "--base" in r.output
    assert "--base-offset" in r.output
    assert "--base-offset-map" in r.output
    assert "--apply" in r.output


def test_infer_base_reg_from_unique_offset_discrepancy():
    from src.cli.struct import _infer_base_reg_from_discrepancies

    reg, source, reason = _infer_base_reg_from_discrepancies([
        {"base_reg": "r31", "cur_disp": 0x10, "ref_disp": 0x18},
        {"base_reg": "r31", "cur_disp": 0x14, "ref_disp": 0x1C},
        {"base_reg": "r1", "cur_disp": 0x8, "ref_disp": 0x8},
    ])

    assert reg == "r31"
    assert source == "unique-offset-discrepancy"
    assert reason is None


def test_infer_base_reg_reports_ambiguous_candidates():
    from src.cli.struct import _infer_base_reg_from_discrepancies

    reg, source, reason = _infer_base_reg_from_discrepancies([
        {"base_reg": "r30", "cur_disp": 0x10, "ref_disp": 0x18},
        {"base_reg": "r31", "cur_disp": 0x14, "ref_disp": 0x1C},
    ])

    assert reg is None
    assert source is None
    assert "ambiguous" in reason
    assert "r30" in reason and "r31" in reason


def test_infer_base_offset_from_layout_unique_fit():
    from src.cli.struct import _infer_base_offset_from_layout

    layout = {
        "components[0].predDC": 0x838,
        "components[0].DCTableSelector": 0x83C,
        "RST": 0x900,
    }
    offset, source, candidates = _infer_base_offset_from_layout(
        layout,
        [
            {"cur_disp": 0x0, "ref_disp": 0x6},
            {"cur_disp": 0x4, "ref_disp": 0xA},
        ],
    )

    assert offset == 0x838
    assert source == "unique-layout-fit"
    assert candidates == [0x838]


def test_infer_base_offset_from_layout_keeps_zero_when_ambiguous():
    from src.cli.struct import _infer_base_offset_from_layout

    layout = {
        "a": 0x10,
        "b": 0x20,
    }
    offset, source, candidates = _infer_base_offset_from_layout(
        layout,
        [{"cur_disp": 0x0, "ref_disp": 0x4}],
    )

    assert offset == 0
    assert source == "ambiguous-layout-fit"
    assert candidates == [0x10, 0x20]


def test_finding_from_offset_discrepancy_normalizes_interior_offset():
    from src.cli.struct import _finding_from_offset_discrepancy

    finding = _finding_from_offset_discrepancy(
        "fn",
        {"base_reg": "r29", "cur_disp": 0x0, "ref_disp": 0x6},
        {"components[0].predDC": 0x838, "components[0].quantTableSelector": 0x83E},
        base_offset=0x838,
        base_offset_source="cli",
        base_reg="r29",
        base_reg_source="unique-offset-discrepancy",
    )

    assert finding["field"] == "components[0].predDC"
    assert finding["current"] == 0x838
    assert finding["expected"] == 0x83E
    assert finding["cur_disp"] == 0
    assert finding["ref_disp"] == 6
    assert finding["base_reg"] == "r29"
    assert finding["base_offset"] == 0x838
    assert finding["ref_field"] == "components[0].quantTableSelector"


def test_struct_verify_cli_infers_base_without_option(monkeypatch):
    from typer.testing import CliRunner
    from src.cli import struct as struct_mod
    from src.cli.struct import struct_app
    from src.common import struct_layout

    monkeypatch.setattr(struct_mod, "get_agent_melee_root", lambda: REPO)
    monkeypatch.setattr(struct_layout, "resolve_layout", lambda repo, name, tu: {"field": 0x10})

    class Result:
        stdout = json.dumps({
            "classification": {
                "offset_discrepancies": [
                    {"base_reg": "r31", "mnemonic": "lwz", "cur_disp": 0x10, "ref_disp": 0x18},
                ],
            },
        })

    monkeypatch.setattr(struct_mod.subprocess, "run", lambda *args, **kwargs: Result())

    r = CliRunner().invoke(
        struct_app,
        ["verify", "fn_80000000", "--struct", "Fake", "--tu-src", "fake.c", "--json"],
    )

    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["findings"][0]["field"] == "field"
    assert data["findings"][0]["base_reg"] == "r31"
    assert data["findings"][0]["base_reg_source"] == "unique-offset-discrepancy"


def test_struct_verify_cli_applies_base_offset(monkeypatch):
    from typer.testing import CliRunner
    from src.cli import struct as struct_mod
    from src.cli.struct import struct_app
    from src.common import struct_layout

    monkeypatch.setattr(struct_mod, "get_agent_melee_root", lambda: REPO)
    monkeypatch.setattr(struct_layout, "resolve_layout", lambda repo, name, tu: {"inner.field": 0x120})

    class Result:
        stdout = json.dumps({
            "classification": {
                "offset_discrepancies": [
                    {"base_reg": "r30", "mnemonic": "stw", "cur_disp": 0x20, "ref_disp": 0x24},
                ],
            },
        })

    monkeypatch.setattr(struct_mod.subprocess, "run", lambda *args, **kwargs: Result())

    r = CliRunner().invoke(
        struct_app,
        [
            "verify",
            "fn_80000000",
            "--struct", "Fake",
            "--base", "r30",
            "--base-offset", "0x100",
            "--tu-src", "fake.c",
            "--json",
        ],
    )

    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["findings"][0]["current"] == 0x120
    assert data["findings"][0]["expected"] == 0x124
    assert data["findings"][0]["base_offset"] == 0x100
    assert data["findings"][0]["base_offset_source"] == "cli"


def test_apply_padding_rejects_nested_field(tmp_path):
    from src.cli.struct import _apply_struct_padding

    header = tmp_path / "fake.h"
    header.write_text("typedef unsigned char u8;\nstruct Fake {\n    int parent;\n};\n")

    result = _apply_struct_padding(
        header,
        "nested.field",
        delta=4,
        verify=lambda: True,
    )

    assert result["status"] == "not_applicable"
    assert "top-level" in result["reason"]
    assert header.read_text() == "typedef unsigned char u8;\nstruct Fake {\n    int parent;\n};\n"


def test_apply_padding_restores_header_when_verify_fails(tmp_path):
    from src.cli.struct import _apply_struct_padding

    header = tmp_path / "fake.h"
    original = "typedef unsigned char u8;\nstruct Fake {\n    int target;\n};\n"
    header.write_text(original)

    result = _apply_struct_padding(
        header,
        "target",
        delta=4,
        verify=lambda: False,
    )

    assert result["status"] == "failed"
    assert "verification" in result["reason"]
    assert header.read_text() == original


def test_apply_padding_inserts_top_level_pad_when_verified(tmp_path):
    from src.cli.struct import _apply_struct_padding

    header = tmp_path / "fake.h"
    header.write_text("typedef unsigned char u8;\nstruct Fake {\n    int target;\n};\n")

    result = _apply_struct_padding(
        header,
        "target",
        delta=4,
        verify=lambda: True,
    )

    assert result["status"] == "applied"
    text = header.read_text()
    assert "u8 pad_struct_verify_target[4];" in text
    assert text.index("pad_struct_verify_target") < text.index("target;")


def test_apply_padding_scopes_duplicate_field_to_target_struct(tmp_path):
    from src.cli.struct import _apply_struct_padding

    header = tmp_path / "fake.h"
    header.write_text(
        "typedef unsigned char u8;\n"
        "struct Other {\n"
        "    int target;\n"
        "};\n"
        "struct Fake {\n"
        "    int target;\n"
        "};\n"
    )

    result = _apply_struct_padding(
        header,
        "target",
        delta=4,
        verify=lambda: True,
        struct_name="Fake",
    )

    assert result["status"] == "applied"
    text = header.read_text()
    assert text.count("pad_struct_verify_target") == 1
    assert text.index("struct Fake") < text.index("pad_struct_verify_target")


# ---------------------------------------------------------------------------
# Task 3.4: _render_verify_table smoke test
# ---------------------------------------------------------------------------

def test_render_verify_table_smoke(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "RST", "current": 0x740, "expected": 0x900,
          "expecteds": [0x900], "n_functions": 1, "functions": ["f"],
          "conflict": False, "confidence": "low"}],
        [],
    )
    out = capsys.readouterr().out
    assert "RST" in out and "0x900" in out


def test_render_verify_table_conflict(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "RST", "current": 0x740, "expected": None,
          "expecteds": [0x900, 0x123], "n_functions": 2, "functions": ["f1", "f2"],
          "conflict": True, "confidence": "low"}],
        [("skippedFn", "no base")],
    )
    out = capsys.readouterr().out
    assert "CONFLICT" in out
    assert "skipped" in out


def test_render_verify_table_high_confidence(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "nMCU", "current": 0x742, "expected": 0x8fc,
          "expecteds": [0x8fc], "n_functions": 2, "functions": ["f1", "f2"],
          "conflict": False, "confidence": "high"}],
        [],
    )
    out = capsys.readouterr().out
    assert "nMCU" in out and "high" in out


def test_render_verify_table_ambiguous(capsys):
    from src.cli.struct import _render_verify_table
    _render_verify_table(
        [{"field": "predDC", "current": 0x100, "expected": 0x110,
          "expecteds": [0x110], "n_functions": 1, "functions": ["f1"],
          "conflict": False, "confidence": "low", "ambiguous": True}],
        [],
    )
    out = capsys.readouterr().out
    assert "predDC" in out and "AMBIGUOUS" in out


# ---------------------------------------------------------------------------
# Task 4.1: End-to-end golden against the pre-fix THPDec layout
# ---------------------------------------------------------------------------

@pytest.mark.slow
@_LIVE_GUARD
def test_struct_verify_thpdec_reports_known_discrepancies(tmp_path):
    """Dogfood: pre-fix thp.h must trigger detection of components[*].predDC offset bug.

    The struct fix is committed at bb81aecd2.  We use 'git show bb81aecd2^:...'
    to get the exact pre-fix header — more robust than string-replace.  The
    finally block ALWAYS restores thp.h to HEAD and rebuilds THPDec.o, even if
    the assertions fail, so the working tree is left clean.
    """
    hdr = REPO / "extern/dolphin/include/dolphin/thp/thp.h"
    thp_src = "extern/dolphin/src/dolphin/thp/THPDec.c"
    thp_obj = "build/GALE01/src/dolphin/thp/THPDec.o"

    # Back up the current (fixed) header to a temp file so we can restore.
    backup = tmp_path / "thp.h.fixed"
    shutil.copy(hdr, backup)

    try:
        # --- Install the pre-fix header (bb81aecd2's parent) ---
        pre_fix_content = subprocess.run(
            ["git", "show", "bb81aecd2^:extern/dolphin/include/dolphin/thp/thp.h"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        hdr.write_text(pre_fix_content)

        # Rebuild THPDec.o with the pre-fix struct layout.
        subprocess.run(["touch", thp_src], cwd=REPO, check=True)
        subprocess.run(
            ["ninja", thp_obj],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )

        # --- Run struct verify via CliRunner (JSON mode) ---
        from typer.testing import CliRunner
        from src.cli.struct import struct_app

        runner = CliRunner()
        result = runner.invoke(
            struct_app,
            [
                "verify",
                "thp/THPDec",
                "--struct", "THPFileInfo",
                "--base", "r3",
                "--tu-src", thp_src,
                "--json",
            ],
        )
        assert result.exit_code == 0, f"struct verify failed:\n{result.output}"
        data = json.loads(result.output)
        fields = {f["field"]: f for f in data["findings"]}

        # Known discrepancies from the pre-fix layout:
        # 1. components[*].predDC: was at offset +0 inside THPComponent, now +6
        assert "components[0].predDC" in fields, (
            f"Expected 'components[0].predDC' discrepancy not found; got: {list(fields)}"
        )
        pre_dc = fields["components[0].predDC"]
        assert pre_dc["current"] == 0x838, f"components[0].predDC current should be 0x838, got 0x{pre_dc['current']:x}"
        assert pre_dc["expected"] == 0x83e, f"components[0].predDC expected should be 0x83e, got 0x{pre_dc['expected']:x}"

        # 2. RST / nMCU / currMCU at wrong offsets (from __THPRestartDefinition / __THPHuffGenerateCodeTable etc.)
        # At minimum one of these should appear (they appear in __THPRestartDefinition
        # which uses base r3 directly).
        rst_or_nmcu = {"RST", "nMCU", "currMCU"}
        found = rst_or_nmcu & set(fields)
        assert found, (
            f"Expected at least one of {rst_or_nmcu} in discrepancies; got: {list(fields)}"
        )

        # Low-offset false positives for 'file', 'currByte', 'cnt' (from the bit-reader)
        # should be ABSENT from the non-ambiguous, non-conflict findings.
        low_fp = {"file", "currByte", "cnt"}
        for fp_field in low_fp:
            if fp_field in fields:
                entry = fields[fp_field]
                # If present, it must be marked ambiguous or conflict — NOT a clean finding.
                assert entry.get("conflict") or entry.get("ambiguous"), (
                    f"Low-offset field {fp_field!r} appeared as a clean finding: {entry}"
                )

    finally:
        # ALWAYS restore the fixed header and rebuild, even on assertion failure.
        shutil.copy(backup, hdr)
        subprocess.run(["touch", thp_src], cwd=REPO, check=False)
        subprocess.run(
            ["ninja", thp_obj],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
