"""Tests for targeted final-only stack-home diagnostics."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.stack_home_explorer import explore_stack_homes


runner = CliRunner()


PCDUMP = textwrap.dedent(
    """\
    Starting function fn_80000001
    BEFORE REGISTER COLORING
    fn_80000001
    B0: Succ={} Pred={} Labels={}
        fmr     f41,f48
        fadds   f50,f60,f63
        fmr     f55,f50
        fmr     f57,f50
    [COALESCE] enter class=1 n_virtuals=81
    [COALESCE] natural mappings (virt -> root):
      48 -> 41
      55 -> 50
      57 -> 50
    [COALESCE] exit class=1 n_virtuals=81 distinct_roots=78 forced=0
    SIMPLIFY GRAPH (class=1, n_colors=32, n_class_regs=81)
      iter ig_idx degree arraySize flags notes
        0 50 14 34 0x0a SPILLED
        1 41 0 2 0x0a SPILLED
    COLORGRAPH DECISIONS (class=1, result=1, n_nodes=81)
      iter ig_idx phys degree nIntfr flags
        0 50 r31 14 34 0x0a  [ROOT]
          interferers: 41=r0
        1 41 r0 0 2 0x0a  [ROOT]
          interferers: 50=r31
    COALESCED ALIASES (alias_idx -> root_idx [root_phys]):
        48 -> 41 [r0]
        55 -> 50 [r31]
        57 -> 50 [r31]
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000001
    B0: Succ={} Pred={} Labels={}
        stwu    r1,-168(r1)
        frsp    f0,f0
        stfs    f0,@810(r1); fIsVolatile
        lfs     f31,@810(r1); fIsVolatile
        blr
    """
)


SOURCE = textwrap.dedent(
    """\
    void fn_80000001(float a, float b, float c)
    {
        float sum;
        float copied;
        copied = a;
        sum = b + c;
        sink(sum + copied);
    }
    """
)


LOCALIZER = {
    "frame_size": 168,
    "mismatch_count": 2,
    "deltas": [4, 4],
    "mismatches": [
        {
            "opcode": "stfs",
            "expected_offset": 0x34,
            "current_offset": 0x30,
            "delta": 4,
        },
        {
            "opcode": "lfs",
            "expected_offset": 0x34,
            "current_offset": 0x30,
            "delta": 4,
        },
    ],
}


def test_stack_home_explorer_reports_fpr_lifetime_cluster_and_suggestions() -> None:
    report = explore_stack_homes(
        PCDUMP,
        "fn_80000001",
        LOCALIZER,
        source_text=SOURCE,
        source_file="src/melee/pl/plbonuslib.c",
    )

    assert report["status"] == "ok"
    assert report["target_count"] == 2
    assert report["ranking"]["primary_objective"] == "target-stack-home-offset"
    assert report["ranking"]["overall_match_percent_used"] is False

    targets = {target["opcode"]: target for target in report["targets"]}
    stfs = targets["stfs"]
    assert stfs["current_offset"] == 0x30
    assert stfs["expected_offset"] == 0x34
    assert stfs["register_class"] == 1
    assert stfs["register_class_name"] == "fpr"
    assert stfs["virtual_token"] == "f41"
    assert stfs["assigned_reg"] == "f0"
    assert stfs["site_kind"] == "final-only-stack-home"
    assert stfs["lifetime"]["first_occurrence"]["opcode"] == "fmr"

    lfs = targets["lfs"]
    assert lfs["virtual_token"] == "f50"
    assert lfs["assigned_reg"] == "f31"
    assert lfs["lifetime"]["first_occurrence"]["opcode"] == "fadds"
    assert lfs["aliases"]["natural"] == [
        {"alias": 55, "root": 50},
        {"alias": 57, "root": 50},
    ]

    neighbor_offsets = {
        neighbor["offset"]
        for target in report["targets"]
        for neighbor in target["neighboring_stack_homes"]
    }
    assert {0x30, 0x34} <= neighbor_offsets

    suggestion_kinds = {
        suggestion["kind"]
        for target in report["targets"]
        for suggestion in target["suggestions"]
    }
    assert "introduce-named-float-temp" in suggestion_kinds
    assert "split-binary-float-expression" in suggestion_kinds
    assert "remove-or-inline-copy-temp" in suggestion_kinds
    assert all(
        suggestion["target_offset_objective"]["overall_match_percent"] is None
        for target in report["targets"]
        for suggestion in target["suggestions"]
    )


def test_stack_home_explorer_cli_consumes_checkdiff_json(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(PCDUMP)
    source = tmp_path / "source.c"
    source.write_text(SOURCE)
    checkdiff = tmp_path / "checkdiff.json"
    checkdiff.write_text(json.dumps({"stack_slot_localizer": LOCALIZER}))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "stack-homes",
            "-f",
            "fn_80000001",
            str(pcdump),
            "--checkdiff-json",
            str(checkdiff),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["targets"][0]["register_class_name"] == "fpr"
    assert payload["targets"][0]["suggestions"][0]["rank"] == 1
