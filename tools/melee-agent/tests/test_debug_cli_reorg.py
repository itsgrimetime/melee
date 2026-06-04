"""CLI surface tests for the workflow-oriented mwcc-debug command layout."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug import tier3_search as tier3_mod

runner = CliRunner()


def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


def test_debug_help_shows_only_workflow_groups() -> None:
    result = runner.invoke(app, ["debug", "--help"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    for group in ("dump", "inspect", "target", "suggest", "mutate", "permute", "util"):
        assert group in out
    assert "Collect pcdumps" in out
    assert "Read, compare, and explain" in out
    assert "Define and score allocator targets" in out

    for removed in (
        "pcdump-local",
        "derive-target",
        "verify-perm",
        "triage-perm",
        "suggest-coalesce-source",
        "pattern-catalog",
        "verify-with-name-magic",
    ):
        assert removed not in out


def test_representative_grouped_command_help_works() -> None:
    commands = [
        ["debug", "dump", "local", "--help"],
        ["debug", "dump", "remote", "--help"],
        ["debug", "dump", "doctor", "--help"],
        ["debug", "dump", "restore-object-report", "--help"],
        ["debug", "inspect", "guide", "--help"],
        ["debug", "inspect", "asm", "--help"],
        ["debug", "inspect", "frame-reservations", "--help"],
        ["debug", "inspect", "var-to-virtual", "--help"],
        ["debug", "inspect", "virtual-to-var", "--help"],
        ["debug", "inspect", "virtual-to-ig", "--help"],
        ["debug", "inspect", "trace-copy", "--help"],
        ["debug", "inspect", "diagnose", "--help"],
        ["debug", "inspect", "explain-virtual", "--help"],
        ["debug", "inspect", "explain-schedule", "--help"],
        ["debug", "inspect", "stack-homes", "--help"],
        ["debug", "target", "derive", "--help"],
        ["debug", "target", "match-iter-first", "--help"],
        ["debug", "target", "score-source", "--help"],
        ["debug", "suggest", "frame", "--help"],
        ["debug", "suggest", "coalesce", "--help"],
        ["debug", "suggest", "schedule", "--help"],
        ["debug", "suggest", "inlines", "--help"],
        ["debug", "mutate", "decl-orders", "--help"],
        ["debug", "mutate", "lifetime-layout", "--help"],
        ["debug", "permute", "run", "--help"],
        ["debug", "permute", "doctor", "--help"],
        ["debug", "permute", "verify", "--help"],
        ["debug", "permute", "remote", "--help"],
        ["debug", "permute", "remote", "doctor", "--help"],
        ["debug", "permute", "remote", "submit", "--help"],
        ["debug", "permute", "remote", "fetch", "--help"],
        ["debug", "util", "name-magic", "--help"],
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, (command, result.stdout)


def test_frame_reservations_cli_reports_extra_low_gap(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            mflr r0
            stw r0,4(r1)
            stwu r1,-88(r1)
            stfd f31,80(r1)
            stmw r26,40(r1)
            lmw r26,40(r1)
            lfd f31,80(r1)
            addi r1,r1,88
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */    mflr r0
        /* 80000004 */    stw r0, 0x4(r1)
        /* 80000008 */    stwu r1, -0x98(r1)
        /* 8000000C */    stfd f31, 0x90(r1)
        /* 80000010 */    stmw r26, 0x68(r1)
        /* 80000014 */    lmw r26, 0x68(r1)
        /* 80000018 */    lfd f31, 0x90(r1)
        /* 8000001C */    addi r1, r1, 0x98
        .endfn fn_80000000
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000000",
            str(pcdump),
            "--expected-asm",
            str(expected),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["frame_delta"] == 64
    assert payload["extra_low_frame_reservation"] == {
        "start": 40,
        "end": 104,
        "size": 64,
        "origin": "implicit-frame-reservation",
        "current_accesses_in_range": [],
    }
    assert "no current pcode stack access" in payload["summary"]


def test_frame_reservations_cli_reports_stack_home_assignments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f0,tmp(r1)
            lfs     f1,tmp(r1)
            stw     r3,cursor(r1)
            addi    r1,r1,80
    """))
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 01 00 30 \tstfs    f0,48(r1)
        +008: c0 21 00 30 \tlfs     f1,48(r1)
        +00c: 90 61 00 34 \tstw     r3,52(r1)
        +010: 38 21 00 50 \taddi    r1,r1,80
    """)
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_current_asm",
        lambda function, melee_root=None: current_asm,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000000",
            str(pcdump),
            "--no-expected",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["current"]["stack_home_assignment_status"] == (
        "resolved-symbolic-homes"
    )
    assert [
        item["symbol"]
        for item in payload["current"]["stack_home_assignments"]
    ] == ["tmp", "cursor"]
    assert payload["current"]["stack_home_assignments"][0]["access_count"] == 2
    assert payload["current"]["stack_home_assignments"][0]["opcodes"] == [
        "lfs",
        "stfs",
    ]
    assert payload["current"]["stack_home_order_summary"] == {
        "status": "computed",
        "has_order_mismatch": False,
        "assignment_count": 2,
        "max_abs_order_delta": 0,
        "assignments": [
            {
                "symbol": "tmp",
                "assignment_order": 0,
                "offset_order": 0,
                "order_delta": 0,
                "offset": 0x30,
                "size": 4,
                "kind": "local-or-temporary",
            },
            {
                "symbol": "cursor",
                "assignment_order": 1,
                "offset_order": 1,
                "order_delta": 0,
                "offset": 0x34,
                "size": 4,
                "kind": "local-or-temporary",
            },
        ],
    }


def test_frame_reservations_cli_text_reports_stack_home_order_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,lenCol+8(r1)
            stfs    f5,lenCol+12(r1)
            stfs    f6,q3(r1)
            addi    r1,r1,80
    """))
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: d0 a1 00 34 \tstfs    f5,52(r1)
        +00c: d0 c1 00 28 \tstfs    f6,40(r1)
        +010: 38 21 00 50 \taddi    r1,r1,80
    """)
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_current_asm",
        lambda function, melee_root=None: current_asm,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000000",
            str(pcdump),
            "--no-expected",
        ],
    )

    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "stack-home assignment order: mismatch" in out
    assert "assignments: 3, max order delta: 2" in out
    assert "q3: assign #2, offset #0, delta -2, offset 0x28" in out
    assert "lenCol+8: assign #0, offset #1, delta +1, offset 0x30" in out
    assert "reorder verdict: unknown-unvalidated" in out
    assert "candidate reorder levers: first-use-order, lifetime-boundary, decl-order-proxy" in out


def test_frame_reservations_cli_text_reports_expected_stack_home_offsets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000002
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000002
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,a(r1)
            stfs    f5,b(r1)
            stfs    f6,c(r1)
            addi    r1,r1,80
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000002, global
        /* 80000000 */    stwu r1, -80(r1)
        /* 80000004 */    stfs f4, 40(r1)
        /* 80000008 */    stfs f5, 52(r1)
        /* 8000000c */    stfs f6, 48(r1)
        /* 80000010 */    addi r1, r1, 80
        .endfn fn_80000002
    """))
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: d0 a1 00 34 \tstfs    f5,52(r1)
        +00c: d0 c1 00 28 \tstfs    f6,40(r1)
        +010: 38 21 00 50 \taddi    r1,r1,80
    """)
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_current_asm",
        lambda function, melee_root=None: current_asm,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000002",
            str(pcdump),
            "--expected-asm",
            str(expected),
        ],
    )

    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "target stack-home offsets: mismatch" in out
    assert (
        "target assignments: 3, max target order delta: 1, max offset delta: 8"
        in out
    )
    assert (
        "c: assign #2, target offset #1, target order delta -1, "
        "offset 0x28 -> 0x30 (-8)"
    ) in out
    assert (
        "a: assign #0, target offset #0, target order delta 0, "
        "offset 0x30 -> 0x28 (+8)"
    ) in out
    assert "target permutation: c, a, b -> a, c, b" in out
    assert "cycle: c -> a" in out
    assert "reorder verdict: unknown-unvalidated" in out
    assert (
        "probe operators: declaration-use-distance, block-scope, "
        "call-argument-tempization, decl-orders"
    ) in out
    assert (
        "next probe: melee-agent debug mutate lifetime-layout -f fn_80000002 "
        "--operator declaration-use-distance --operator block-scope "
        "--operator call-argument-tempization --compile-probes --json"
    ) in out



def test_frame_reservations_cli_evaluates_probe_results_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000002
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000002
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,a(r1)
            stfs    f5,b(r1)
            stfs    f6,c(r1)
            addi    r1,r1,80
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000002, global
        /* 80000000 */    stwu r1, -80(r1)
        /* 80000004 */    stfs f4, 40(r1)
        /* 80000008 */    stfs f5, 52(r1)
        /* 8000000c */    stfs f6, 48(r1)
        /* 80000010 */    addi r1, r1, 80
        .endfn fn_80000002
    """))
    probe_results = tmp_path / "probes.json"
    probe_results.write_text(json.dumps({
        "variants": [
            {
                "label": "swap-cycle",
                "operator": "declaration-use-distance",
                "status": "ok",
                "match_percent": 99.91,
                "stack_slot_localizer": {
                    "mismatch_count": 0,
                    "mismatches": [],
                },
            }
        ]
    }))
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: d0 a1 00 34 \tstfs    f5,52(r1)
        +00c: d0 c1 00 28 \tstfs    f6,40(r1)
        +010: 38 21 00 50 \taddi    r1,r1,80
    """)
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_current_asm",
        lambda function, melee_root=None: current_asm,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000002",
            str(pcdump),
            "--expected-asm",
            str(expected),
            "--probe-results-json",
            str(probe_results),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    evaluation = payload["stack_home_probe_evaluation"]
    assert evaluation["verdict"] == "source-reachable-reorder"
    assert evaluation["stop_condition"]["kind"] == "validated-source-reorder"
    assert evaluation["best_variant"]["label"] == "swap-cycle"
    assert evaluation["best_variant"]["target_fixed"] is True


def test_frame_reservations_cli_reports_current_low_expansion(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function gm_801A9DD0
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        gm_801A9DD0
        B0: Succ={} Pred={} Labels={}
            stw r0,4(r1)
            stwu r1,-152(r1)
            stfd f31,144(r1)
            stfd f30,136(r1)
            stw r8,40(r1)
            stw r7,28(r1)
            stw r9,72(r1)
            lfd f0,72(r1)
            stw r9,80(r1)
            lfd f0,80(r1)
            lfd f30,136(r1)
            lfd f31,144(r1)
            addi r1,r1,152
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn gm_801A9DD0, global
        /* 801A9DD8 */    stw r0, 0x4(r1)
        /* 801A9DDC */    stwu r1, -0x90(r1)
        /* 801A9DE0 */    stfd f31, 0x88(r1)
        /* 801A9DE4 */    stfd f30, 0x80(r1)
        /* 801A9DE8 */    stw r8, 0x24(r1)
        /* 801A9DEC */    stw r7, 0x18(r1)
        /* 801A9DF0 */    stw r9, 0x40(r1)
        /* 801A9DF4 */    lfd f0, 0x40(r1)
        /* 801A9DF8 */    stw r9, 0x48(r1)
        /* 801A9DFC */    lfd f0, 0x48(r1)
        /* 801A9E00 */    lfd f30, 0x80(r1)
        /* 801A9E04 */    lfd f31, 0x88(r1)
        /* 801A9E08 */    addi r1, r1, 0x90
        .endfn gm_801A9DD0
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "gm_801A9DD0",
            str(pcdump),
            "--expected-asm",
            str(expected),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "cause: stack-object-offset-shift (medium)" in result.stdout
    assert "verdict: source-reachable-candidate" in result.stdout
    assert "current low-frame expansion: 0x18-0x1c (4 bytes)" in result.stdout
    assert "alignment growth bytes: 4" in result.stdout
    assert "current non-save stack accesses in range: none" in result.stdout


def test_frame_residual_hint_routes_register_clean_stack_growth() -> None:
    report = {
        "function": "gm_801A9DD0",
        "summary": (
            "gm_801A9DD0: expected frame=144, current frame=152; "
            "current has an implicit unused low local home "
            "(0x18-0x1c, 4 bytes) plus 4 bytes of alignment growth"
        ),
        "current": {"frame_size": 152},
        "expected": {"frame_size": 144},
        "frame_delta": -8,
        "extra_low_frame_reservation": None,
        "current_low_frame_expansion": {
            "start": 24,
            "end": 28,
            "size": 4,
            "origin": "implicit-current-low-local-home",
            "current_accesses_in_range": [],
        },
    }

    hint = debug_cli._frame_residual_hint_from_report(report)

    assert hint is not None
    assert hint["kind"] == "frame-local-area"
    assert "not register allocation" in hint["message"]
    assert "debug inspect frame-reservations -f gm_801A9DD0" in hint["next_steps"][0]
    assert "--force-frame-from-diff" in hint["next_steps"][1]


def test_target_score_dump_json_includes_frame_component(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-152(r1)
            stw r31,40(r1)
            addi r1,r1,152
    """))
    target = tmp_path / "target.json"
    target.write_text(json.dumps({
        "function": "fn_80000000",
        "virtuals": {},
        "frame": {"frame_size": 144},
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "score-dump",
            "-f",
            "fn_80000000",
            "--target",
            str(target),
            str(pcdump),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame_targeted"] is True
    assert payload["frame_size_actual"] == 152
    assert payload["frame_size_target"] == 144
    assert payload["frame_size_distance"] == 8
    assert payload["frame_penalty"] > 0


def test_target_derive_can_override_frame_from_checkdiff_target_asm(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function gm_801A9DD0
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        gm_801A9DD0
        B0: Succ={} Pred={} Labels={}
            stwu r1,-152(r1)
            stw r8,40(r1)
            addi r1,r1,152
    """))
    checkdiff_json = tmp_path / "checkdiff.json"
    checkdiff_json.write_text(json.dumps({
        "target_asm": [
            "<gm_801A9DD0>:",
            "+014: 94 21 ff 70 \tstwu    r1,-144(r1)",
            "+060: 91 01 00 24 \tstw     r8,36(r1)",
            "+1f0: 38 21 00 90 \taddi    r1,r1,144",
        ],
        "current_asm": [
            "<gm_801A9DD0>:",
            "+014: 94 21 ff 68 \tstwu    r1,-152(r1)",
            "+060: 91 01 00 28 \tstw     r8,40(r1)",
            "+1f0: 38 21 00 98 \taddi    r1,r1,152",
        ],
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "derive",
            "-f",
            "gm_801A9DD0",
            str(pcdump),
            "--frame-from-checkdiff",
            str(checkdiff_json),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame"]["frame_size"] == 144
    assert {
        "start": 36,
        "end": 40,
        "size": 4,
        "kind": "local-or-temporary",
    } in payload["frame"]["access_ranges"]


def test_suggest_frame_reports_low_home_source_levers(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function gm_801A9DD0
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        gm_801A9DD0
        B0: Succ={} Pred={} Labels={}
            stw r0,4(r1)
            stwu r1,-152(r1)
            stfd f31,144(r1)
            stfd f30,136(r1)
            stw r8,40(r1)
            stw r7,28(r1)
            stw r9,72(r1)
            lfd f0,72(r1)
            stw r9,80(r1)
            lfd f0,80(r1)
            lfd f30,136(r1)
            lfd f31,144(r1)
            addi r1,r1,152
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn gm_801A9DD0, global
        /* 801A9DD8 */    stw r0, 0x4(r1)
        /* 801A9DDC */    stwu r1, -0x90(r1)
        /* 801A9DE0 */    stfd f31, 0x88(r1)
        /* 801A9DE4 */    stfd f30, 0x80(r1)
        /* 801A9DE8 */    stw r8, 0x24(r1)
        /* 801A9DEC */    stw r7, 0x18(r1)
        /* 801A9DF0 */    stw r9, 0x40(r1)
        /* 801A9DF4 */    lfd f0, 0x40(r1)
        /* 801A9DF8 */    stw r9, 0x48(r1)
        /* 801A9DFC */    lfd f0, 0x48(r1)
        /* 801A9E00 */    lfd f30, 0x80(r1)
        /* 801A9E04 */    lfd f31, 0x88(r1)
        /* 801A9E08 */    addi r1, r1, 0x90
        .endfn gm_801A9DD0
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "frame",
            "-f",
            "gm_801A9DD0",
            str(pcdump),
            "--expected-asm",
            str(expected),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame"]["current_low_frame_expansion"]["origin"] == (
        "implicit-current-low-local-home"
    )
    assert payload["suggestions"][0]["kind"] == "suppress-unused-local-home"
    assert "held FP constant" in payload["suggestions"][0]["description"]
    joined_commands = "\n".join(
        command
        for suggestion in payload["suggestions"]
        for command in suggestion["commands"]
    )
    assert "debug target score-source" in joined_commands
    assert "tools/checkdiff.py gm_801A9DD0 --format json --no-build" in joined_commands
    assert "--frame-from-checkdiff gm_801A9DD0.checkdiff.json" in joined_commands
    assert "--force-frame-from-diff" in joined_commands


def test_first_divergence_frame_mode_reports_low_home_case(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function gm_801A9DD0
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        gm_801A9DD0
        B0: Succ={} Pred={} Labels={}
            stw r0,4(r1)
            stwu r1,-152(r1)
            stfd f31,144(r1)
            stfd f30,136(r1)
            stw r8,40(r1)
            stw r7,28(r1)
            stw r9,72(r1)
            lfd f0,72(r1)
            stw r9,80(r1)
            lfd f0,80(r1)
            lfd f30,136(r1)
            lfd f31,144(r1)
            addi r1,r1,152
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn gm_801A9DD0, global
        /* 801A9DD8 */    stw r0, 0x4(r1)
        /* 801A9DDC */    stwu r1, -0x90(r1)
        /* 801A9DE0 */    stfd f31, 0x88(r1)
        /* 801A9DE4 */    stfd f30, 0x80(r1)
        /* 801A9DE8 */    stw r8, 0x24(r1)
        /* 801A9DEC */    stw r7, 0x18(r1)
        /* 801A9DF0 */    stw r9, 0x40(r1)
        /* 801A9DF4 */    lfd f0, 0x40(r1)
        /* 801A9DF8 */    stw r9, 0x48(r1)
        /* 801A9DFC */    lfd f0, 0x48(r1)
        /* 801A9E00 */    lfd f30, 0x80(r1)
        /* 801A9E04 */    lfd f31, 0x88(r1)
        /* 801A9E08 */    addi r1, r1, 0x90
        .endfn gm_801A9DD0
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "first-divergence",
            "-f",
            "gm_801A9DD0",
            str(pcdump),
            "--frame",
            "--expected-asm",
            str(expected),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "FRAME/LOCAL-AREA FACTS" in out
    assert "Case frame-unused-low-home" in out
    assert "current frame: 152" in out
    assert "target frame: 144" in out
    assert "0x18-0x1c (4 bytes)" in out
    assert "debug suggest frame -f gm_801A9DD0" in out
    assert "--force-frame-from-diff" in out


def test_first_divergence_frame_mode_json_reports_next_steps(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function gm_801A9DD0
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        gm_801A9DD0
        B0: Succ={} Pred={} Labels={}
            stw r0,4(r1)
            stwu r1,-152(r1)
            stfd f31,144(r1)
            stfd f30,136(r1)
            stw r8,40(r1)
            stw r7,28(r1)
            stw r9,72(r1)
            lfd f0,72(r1)
            stw r9,80(r1)
            lfd f30,136(r1)
            lfd f31,144(r1)
            addi r1,r1,152
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn gm_801A9DD0, global
        /* 801A9DD8 */    stw r0, 0x4(r1)
        /* 801A9DDC */    stwu r1, -0x90(r1)
        /* 801A9DE0 */    stfd f31, 0x88(r1)
        /* 801A9DE4 */    stfd f30, 0x80(r1)
        /* 801A9DE8 */    stw r8, 0x24(r1)
        /* 801A9DEC */    stw r7, 0x18(r1)
        /* 801A9DF0 */    stw r9, 0x40(r1)
        /* 801A9DF4 */    lfd f0, 0x40(r1)
        /* 801A9DF8 */    stw r9, 0x48(r1)
        /* 801A9DFC */    lfd f0, 0x48(r1)
        /* 801A9E00 */    lfd f30, 0x80(r1)
        /* 801A9E04 */    lfd f31, 0x88(r1)
        /* 801A9E08 */    addi r1, r1, 0x90
        .endfn gm_801A9DD0
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "first-divergence",
            "-f",
            "gm_801A9DD0",
            str(pcdump),
            "--frame",
            "--expected-asm",
            str(expected),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "frame-local-area"
    assert payload["case"] == "frame-unused-low-home"
    assert payload["current_frame"] == 152
    assert payload["target_frame"] == 144
    assert payload["residual"]["range"]["start"] == 24
    assert payload["residual"]["alignment_growth_bytes"] == 4
    assert any("--force-frame-from-diff" in step for step in payload["next_steps"])


def test_dump_remote_quotes_cmd_env_assignments(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}

    class FakePopen:
        def __init__(self, cmd, *, stdout, stderr):
            captured["cmd"] = cmd
            self.stdout = io.BytesIO(b"pcdump fixture")

        def wait(self):
            return 0

    monkeypatch.setattr(
        debug_cli,
        "_resolve_src_relative",
        lambda _path: "src/melee/pl/plbonuslib.c",
    )
    monkeypatch.setattr(debug_cli.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "remote",
            "src/melee/pl/plbonuslib.c",
            "--output",
            str(tmp_path / "pcdump.txt"),
            "--timeout",
            "120",
            "--no-pull",
        ],
    )

    assert result.exit_code == 0
    remote_cmd = captured["cmd"][2]
    assert 'set "MWCC_DEBUG_TIMEOUT_SECS=120"' in remote_cmd
    assert 'set "MWCC_DEBUG_NO_PULL=1"' in remote_cmd
    assert "set MWCC_DEBUG_NO_PULL=1 &&" not in remote_cmd


def test_removed_top_level_debug_commands_are_not_registered() -> None:
    removed_commands = [
        "pcdump",
        "pcdump-local",
        "setup-local",
        "analyze",
        "simulate",
        "diff",
        "guide",
        "stuck",
        "ceiling",
        "rank-callees",
        "var-to-virtual",
        "virtual-to-var",
        "virtual-to-ig",
        "trace-copy",
        "derive-target",
        "score",
        "score-source",
        "match-iter-first",
        "suggest-casts",
        "suggest-coalesce-source",
        "suggest-inlines",
        "verify-perm",
        "enumerate-decl-orders",
        "triage-perm",
        "gen-permuter-config",
        "fix-perm-compile",
        "restore-object-report",
        "tier3-search",
        "pattern-catalog",
        "name-magic",
        "verify-with-name-magic",
    ]
    for command in removed_commands:
        result = runner.invoke(app, ["debug", command, "--help"])
        assert result.exit_code != 0, command
        combined = strip_ansi(result.stdout + result.stderr)
        assert "No such command" in combined or "Got unexpected extra argument" in combined


def test_inspect_help_uses_taxonomy_neutral_diagnose_command() -> None:
    result = runner.invoke(app, ["debug", "inspect", "--help"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "diagnose" in out
    assert "ceiling" not in out


def test_diagnose_spilled_hints_reuse_call_return_copy_chain() -> None:
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
        SIMPLIFY GRAPH (class=0, n_colors=20, n_class_regs=32)
          iter ig_idx degree arraySize flags notes
            0 40 1 1 0x08 SPILLED
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

    hints = debug_cli._diagnose_spilled_virtual_hints(
        pcdump,
        "fn_80000002",
        source,
        source_file="sample.c",
    )

    assert hints == [{
        "virtual": 40,
        "kind": "call-return",
        "confidence": "copy-chain",
        "var_name": "result",
        "source_file": "sample.c",
        "source_line": 4,
        "source_col": 14,
        "expression": "helper_fn(entity)",
        "call_symbol": "helper_fn",
        "copy_chain": [40, 43, 59, 3],
        "first_def": {
            "block_idx": 19,
            "opcode": "bl",
            "operands": "helper_fn",
        },
        "use_sites": [{
            "block_idx": 33,
            "opcode": "cmpi",
            "operands": "cr0,r40,0",
        }],
    }]


def test_diagnose_force_phys_reports_coupled_source_shape_guidance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "pl" / "plbonuslib.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void ftCo_8009E7B4(void) {}\n")
    pcdump = tmp_path / "ftCo_8009E7B4.pcdump.txt"
    pcdump.write_text("Starting function ftCo_8009E7B4\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/pl/plbonuslib",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 99.1)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )
    ledger_path = tmp_path / "attempts.json"
    monkeypatch.setenv("DECOMP_ATTEMPT_LEDGER_FILE", str(ledger_path))
    from src.cli.tracking import record_attempt

    record_attempt(
        "ftCo_8009E7B4",
        match_percent=99.1,
        outcome="blocked",
        classification="register-allocation",
        blocker="b4 tree probes exhausted without source movement",
        note="b4 tree probes and remote permuter produced negative evidence",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "ftCo_8009E7B4",
            "--skip-decl-orders",
            "--force-phys",
            "0:58:4,0:44:4,0:42:3,0:35:30,0:56:29,0:34:30",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "Coupled force-phys proof vector" in out
    assert "early flag/reload temps: r58->r4, r44->r4, r42->r3" in out
    assert (
        "late x594_b4/x594_b3 loop IV/tree-pointer swaps: "
        "r35->r30, r56->r29, r34->r30"
    ) in out
    assert "singleton/prefix force-phys probes can no-match" in out
    assert "multi-site allocator-shape hypothesis" in out
    assert "Source-lever coverage matrix" in out
    assert "early flag/reload block" in out
    assert "x594_b4/x594_b3 field-bit tests" in out
    assert "b4 tree probes exhausted without source movement" in out
    assert "status: negative-evidence" in out
    assert (
        "melee-agent debug dump local src/melee/pl/plbonuslib.c "
        "--force-phys 0:58:4,0:44:4,0:42:3,0:35:30,0:56:29,0:34:30 "
        "--force-phys-fn ftCo_8009E7B4"
    ) in out

    json_result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "ftCo_8009E7B4",
            "--skip-decl-orders",
            "--force-phys",
            "0:58:4,0:44:4,0:42:3,0:35:30,0:56:29,0:34:30",
            "--json",
        ],
    )
    assert json_result.exit_code == 0, json_result.stdout + json_result.stderr
    payload = json.loads(json_result.stdout)
    matrix = payload["coupled_force_phys"]["coverage_matrix"]
    assert matrix[0]["source_regions"][0] == "early flag/reload block"
    assert any(
        family["status"] == "negative-evidence"
        for row in matrix
        for family in row["transform_families"]
    )


def test_permuter_scorer_uses_grouped_score_source_command() -> None:
    script = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        / "scripts"
        / "permute_with_mwcc.py"
    )
    text = script.read_text()
    assert '"debug", "target", "score-source"' in text
    assert '"debug", "score-source"' not in text


def test_resolve_decomp_permuter_root_falls_back_when_perm_root_is_candidate_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = tmp_path / "matcher-worktree"
    requested.mkdir()
    fallback = tmp_path / "code" / "decomp-permuter"
    (fallback / "src").mkdir(parents=True)
    (fallback / "permuter.py").write_text("#!/usr/bin/env python3\n")
    (fallback / "src" / "__init__.py").write_text("")
    (fallback / "src" / "compiler.py").write_text("")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert debug_cli._resolve_decomp_permuter_root(requested) == fallback


def _schedule_pcdump_with_pre_and_final(pre_body: str, final_body: str) -> str:
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


def test_debug_suggest_schedule_outputs_json_suggestions(tmp_path: Path) -> None:
    source = tmp_path / "sample.c"
    real = tmp_path / "real.pcdump"
    forced = tmp_path / "forced.pcdump"
    source.write_text(
        "typedef struct Obj Obj;\n"
        "extern Obj* pl_804D6470;\n"
        "void fn_80000000(void) {\n"
        "    sink(pl_804D6470->x90, pl_804D6470->x94);\n"
        "}\n"
    )
    real.write_text(_schedule_pcdump_with_pre_and_final(
        "    lwz     r40,148(r32)\n"
        "    lwz     r41,144(r32)\n",
        "    lwz     r6,144(r31)\n"
        "    lwz     r7,148(r31)\n",
    ))
    forced.write_text(_schedule_pcdump_with_pre_and_final(
        "    lwz     r40,148(r32)\n"
        "    lwz     r41,144(r32)\n",
        "    lwz     r7,148(r31)\n"
        "    lwz     r6,144(r31)\n",
    ))

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "schedule",
            "-f",
            "fn_80000000",
            "--force-schedule",
            "lwz:0x94>0x90",
            "--pcdump",
            str(real),
            "--against",
            str(forced),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "structural"
    assert payload["suggestions"][0]["kind"] == "split-enclosing-statement"
    assert payload["suggestions"][0]["target_expression"] == "pl_804D6470->x94"

    alias_result = runner.invoke(
        app,
        [
            "debug",
            "suggest-schedule-source",
            "-f",
            "fn_80000000",
            "--force-schedule",
            "lwz:0x94>0x90",
            "--pcdump",
            str(real),
            "--against",
            str(forced),
            "--source-file",
            str(source),
        ],
    )
    assert alias_result.exit_code == 0, alias_result.stdout + alias_result.stderr
    assert "suggest-schedule-source - fn_80000000" in alias_result.stdout


def test_non_natural_checkdiff_env_disables_fingerprint() -> None:
    env = debug_cli._checkdiff_env_without_fingerprint()

    assert env["CHECKDIFF_NO_FINGERPRINT"] == "1"


def test_inspect_asm_prints_current_compiled_assembly(monkeypatch) -> None:
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None):
        calls.append((cmd, cwd, capture_output, text, env))
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "function": "fn_80000000",
                    "current_asm": [
                        "<fn_80000000>:",
                        "+000: li r3, 0",
                        "+004: blr",
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", Path("/repo"))
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(app, ["debug", "inspect", "asm", "-f", "fn_80000000", "--no-build"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "<fn_80000000>:" in out
    assert "+000: li r3, 0" in out
    assert calls[0][0] == [
        "python",
        "tools/checkdiff.py",
        "fn_80000000",
        "--format",
        "json",
        "--no-build",
    ]
    assert calls[0][4]["CHECKDIFF_NO_FINGERPRINT"] == "1"


def test_permuter_missing_dir_hint_uses_extractable_asm(tmp_path: Path) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    (perm_root / ".venv" / "bin").mkdir(parents=True)
    (perm_root / ".venv" / "bin" / "python").write_text("")
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) {}\n")

    hint = debug_cli._permuter_import_hint(
        "fn_80000000",
        perm_root=perm_root,
        melee_root=melee_root,
        unit="melee/mn/sample",
    )

    assert "melee-agent debug permute bootstrap -f fn_80000000" in hint
    assert "--perm-root" in hint
    assert "debug permute fix-compile" in hint


def test_debug_permute_bootstrap_imports_and_writes_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) {}\n")
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")

    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        calls.append((argv, cwd))
        if "import.py" in argv[1]:
            fn_dir = perm_root / "nonmatchings" / "fn_80000000"
            fn_dir.mkdir(parents=True)
            (fn_dir / "base.c").write_text("void fn_80000000(void) {}\n")
            (fn_dir / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (fn_dir / "target.o").write_bytes(b"target")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "bootstrap",
            "-f",
            "fn_80000000",
            "--perm-root",
            str(perm_root),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls[0][0][:5] == [
        "melee-agent",
        "extract",
        "get",
        "fn_80000000",
        "--full",
    ]
    assert "import.py" in calls[1][0][1]
    assert "--preserve-macros" in calls[1][0]
    assert "PAD_STACK" in calls[1][0][calls[1][0].index("--preserve-macros") + 1]
    fn_dir = perm_root / "nonmatchings" / "fn_80000000"
    assert (fn_dir / "settings.toml").exists()
    assert "func_name = \"fn_80000000\"" in (fn_dir / "settings.toml").read_text()


def test_debug_permute_bootstrap_recovers_melee_root_from_install_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) {}\n")
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"units":[{"name":"main/melee/mn/sample",'
        '"functions":[{"name":"fn_80000000"}]}]}'
    )
    package_debug = melee_root / "tools" / "melee-agent" / "src" / "cli" / "debug.py"
    package_debug.parent.mkdir(parents=True)
    package_debug.write_text("# package path marker\n")
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")

    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        calls.append((argv, cwd))
        if "import.py" in argv[1]:
            assert argv[2] == str(src_path)
            fn_dir = perm_root / "nonmatchings" / "fn_80000000"
            fn_dir.mkdir(parents=True)
            (fn_dir / "base.c").write_text(src_path.read_text())
            (fn_dir / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (fn_dir / "target.o").write_bytes(b"target")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", perm_root)
    monkeypatch.setattr(debug_cli, "__file__", str(package_debug))
    monkeypatch.chdir(perm_root)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "bootstrap",
            "-f",
            "fn_80000000",
            "--perm-root",
            str(perm_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["unit"] == "melee/mn/sample"
    assert payload["import_source"] == str(src_path)
    assert calls[0][1] == melee_root


def test_debug_permute_bootstrap_source_file_stages_variant_and_restores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    variant_path = tmp_path / "variant.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) {}\n")
    variant_path.write_text("void fn_80000000(void) { PAD_STACK(64); }\n")
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")

    observed_import_source: list[str] = []

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        if "import.py" in argv[1]:
            observed_import_source.append(src_path.read_text())
            assert argv[2] == str(src_path)
            fn_dir = perm_root / "nonmatchings" / "fn_80000000"
            fn_dir.mkdir(parents=True)
            (fn_dir / "base.c").write_text(src_path.read_text())
            (fn_dir / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (fn_dir / "target.o").write_bytes(b"target")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "bootstrap",
            "-f",
            "fn_80000000",
            "--perm-root",
            str(perm_root),
            "--source-file",
            str(variant_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert observed_import_source == [variant_path.read_text()]
    assert src_path.read_text() == "void fn_80000000(void) {}\n"
    payload = json.loads(result.stdout)
    assert payload["source"] == str(variant_path)
    assert payload["import_source"] == str(src_path)
    assert "PAD_STACK(64)" in (
        perm_root / "nonmatchings" / "fn_80000000" / "base.c"
    ).read_text()


def test_debug_permute_bootstrap_promotes_fresh_worktree_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) { fresh_token(); }\n")
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")

    stale_worktree_dir = melee_root / "nonmatchings" / "fn_80000000"
    stale_worktree_dir.mkdir(parents=True)
    (stale_worktree_dir / "base.c").write_text("stale worktree base\n")

    destination = perm_root / "nonmatchings" / "fn_80000000"
    destination.mkdir(parents=True)
    (destination / "base.c").write_text("stale perm root base\n")
    (destination / "settings.toml").write_text("custom = true\n")
    output_dir = destination / "output-1-1"
    output_dir.mkdir()
    (output_dir / "source.c").write_text("candidate output\n")

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        if "import.py" in argv[1]:
            imported = melee_root / "nonmatchings" / "fn_80000000-2"
            imported.mkdir(parents=True)
            (imported / "base.c").write_text("fresh_token from import\n")
            (imported / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (imported / "target.s").write_text("target asm\n")
            (imported / "target.o").write_bytes(b"target")
            (imported / "settings.toml").write_text("stock = true\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "bootstrap",
            "-f",
            "fn_80000000",
            "--perm-root",
            str(perm_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function_dir"] == str(destination)
    assert (destination / "base.c").read_text() == "fresh_token from import\n"
    assert (destination / "compile.sh").exists()
    assert (destination / "target.o").read_bytes() == b"target"
    assert (destination / "settings.toml").read_text() == "custom = true\n"
    assert (output_dir / "source.c").read_text() == "candidate output\n"
    assert not (melee_root / "nonmatchings" / "fn_80000000-2").exists()


def test_permuter_function_dir_accepts_worktree_import_path(tmp_path: Path) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    worktree_dir = melee_root / "nonmatchings" / "fn_80000000"
    worktree_dir.mkdir(parents=True)

    assert debug_cli._resolve_permuter_function_dir(
        "fn_80000000",
        perm_root=perm_root,
        melee_root=melee_root,
    ) == worktree_dir


def test_debug_permute_doctor_reports_missing_function_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    perm_root.mkdir()

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "doctor",
            "-f",
            "fn_80000000",
            "--perm-root",
            str(perm_root),
        ],
    )

    assert result.exit_code == 2
    out = strip_ansi(result.stdout)
    assert "FAIL\tfunction dir" in out
    assert "melee-agent debug permute bootstrap -f fn_80000000" in out


def test_debug_permute_doctor_passes_ready_function_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    fn_dir = perm_root / "nonmatchings" / "fn_80000000"
    fn_dir.mkdir(parents=True)
    for filename in ("base.c", "compile.sh", "target.o", "settings.toml"):
        (fn_dir / filename).write_text("")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "doctor",
            "-f",
            "fn_80000000",
            "--perm-root",
            str(perm_root),
        ],
    )

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "PASS\tfunction dir" in out
    assert "PASS\tcompile.sh" in out
    assert "ready for `melee-agent debug permute run`" in out


def test_permute_keep_merge_allows_format_only_current_drift() -> None:
    base = """\
void f(void)
{
    result = compute(alpha, beta, gamma);
}
"""
    candidate = """\
void f(void)
{
    result = compute(alpha, beta, delta);
}
"""
    current = """\
void f(void)
{
    result = compute(
        alpha,
        beta,
        gamma);
}
"""

    merged, strategy, conflicts = debug_cli._merge_permuter_keep_candidate(
        base,
        candidate,
        current,
        force=False,
    )

    assert conflicts == []
    assert strategy == "format-normalized-replace"
    assert merged == candidate


def test_debug_permute_triage_reports_placeholder_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    inline_fn();\n}\n"
    )

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "corrupt-candidate"
    assert data["results"][0]["semantic_risk_bucket"] == "repo-invalid"
    assert "inline_fn" in data["results"][0]["first_diag"]
    assert src_path.read_text() == original
    assert calls == [
        ["ninja", "build/GALE01/src/melee/mn/sample.o", "build/GALE01/report.json"]
    ]


def test_debug_permute_verify_json_placeholder_suppresses_failure_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void)\n{\n    inline_fn();\n}\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--keep-failed",
        ],
    )

    assert result.exit_code == 7
    assert json.loads(result.stdout)["status"] == "corrupt-candidate"
    combined = strip_ansi(result.stdout + result.stderr)
    assert "To report this tooling failure for follow-up" not in combined


def test_debug_permute_verify_json_rejects_unsafe_source_risk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    output_dir = tmp_path / "output-1155-2"
    output_dir.mkdir()
    candidate = output_dir / "source.c"
    candidate.write_text(
        "void fn_80000000(void)\n{\n    abs = (abs = -abs);\n}\n"
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
        ],
    )

    assert result.exit_code == 7
    data = json.loads(result.stdout)
    assert data["status"] == "unsafe-candidate"
    assert data["semantic_risk_bucket"] == "semantic-risk-high"
    assert data["source_risks"][0]["kind"] == "repeated-scalar-assignment"
    sidecar = output_dir / "melee-agent-candidate-status.json"
    sidecar_payload = json.loads(sidecar.read_text())
    assert sidecar_payload["status"] == "unsafe-candidate"
    assert sidecar_payload["semantic_risk_bucket"] == "semantic-risk-high"


def test_debug_permute_verify_audits_against_base_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(float delta)\n"
        "{\n"
        "    float abs = delta;\n"
        "    if (abs < 0.0f) {\n"
        "        abs = -abs;\n"
        "    }\n"
        "    table->xD74 += abs;\n"
        "}\n"
    )

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1330-2"
    output_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text(src_path.read_text())
    candidate = output_dir / "source.c"
    candidate.write_text(
        "void fn_80000000(float delta)\n"
        "{\n"
        "    float abs = delta;\n"
        "    if (abs < 0.0f) {\n"
        "        abs = -abs;\n"
        "    }\n"
        "    abs = -abs;\n"
        "    table->xD74 += abs;\n"
        "}\n"
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
        ],
    )

    assert result.exit_code == 7
    data = json.loads(result.stdout)
    assert data["status"] == "unsafe-candidate"
    assert data["semantic_risk_bucket"] == "semantic-risk-high"
    assert data["source_risks"][0]["kind"] == "manual-abs-sign-flip"
    sidecar = output_dir / "melee-agent-candidate-status.json"
    sidecar_payload = json.loads(sidecar.read_text())
    assert sidecar_payload["status"] == "unsafe-candidate"
    assert sidecar_payload["semantic_risk_bucket"] == "semantic-risk-high"


def test_debug_permute_verify_uses_current_source_as_audit_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = (
        "void fn_80000000(int abs)\n"
        "{\n"
        "    abs = abs;\n"
        "    real_call(abs);\n"
        "}\n"
    )
    src_path.write_text(original)

    candidate = tmp_path / "early-guard-return-0.c"
    candidate.write_text(
        "void fn_80000000(int abs)\n"
        "{\n"
        "    abs = abs;\n"
        "    candidate_call(abs);\n"
        "}\n"
    )

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        lambda unit, function, root, fast_report=False, timeout=None: (91.25, None),
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--candidate-timeout",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "ok"
    assert data["source_risks"] == []
    assert src_path.read_text() == original
    status = json.loads(
        (candidate.parent / "melee-agent-candidate-status.json").read_text()
    )
    assert status["status"] == "ok"
    assert status["source_risks"] == []
    assert calls[0] == ["ninja", "build/GALE01/src/melee/mn/sample.o"]


def test_debug_permute_verify_candidate_timeout_restores_and_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    candidate = tmp_path / "source.c"
    candidate.write_text("void fn_80000000(void)\n{\n    candidate_call();\n}\n")

    obj_cmd = ["ninja", "build/GALE01/src/melee/mn/sample.o"]
    calls: list[tuple[list[str], float | None]] = []

    def fake_ninja(cmd, melee_root_arg, *, timeout=None):
        cmd = [str(part) for part in cmd]
        calls.append((cmd, timeout))
        return (
            subprocess.CompletedProcess(
                cmd,
                124,
                "",
                "timed out after 0.01s running ninja sample.o",
            ),
            False,
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        lambda *args, **kwargs: pytest.fail("timed-out builds must not refresh"),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0.01",
            "--json",
        ],
    )

    assert result.exit_code == 4, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "build-timeout"
    assert data["returncode"] == 124
    assert data["source_reverted"] is True
    assert "timed out after 0.01s" in data["first_diag"]
    assert src_path.read_text() == original
    assert calls == [(obj_cmd, 0.01)]
    status = json.loads(
        (candidate.parent / "melee-agent-candidate-status.json").read_text()
    )
    assert status["status"] == "build-timeout"
    assert "timed out after 0.01s" in status["first_diag"]


def test_debug_permute_triage_retries_empty_build_failure_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1265-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    real_call();\n}\n"
    )

    obj_cmd = ["ninja", "build/GALE01/src/melee/mn/sample.o"]
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        calls.append(cmd)
        if cmd == obj_cmd and calls.count(obj_cmd) == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 95.6426)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "ok"
    assert data["results"][0]["semantic_risk_bucket"] == "plausible-C-shape"
    assert data["results"][0]["match_pct"] == 95.6426
    assert calls.count(obj_cmd) == 2


def test_run_ninja_with_timeout_uses_process_tree_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, float]] = []

    def fake_process_tree_runner(cmd, *, cwd, timeout, env=None):
        calls.append(([str(part) for part in cmd], cwd, timeout))
        raise subprocess.TimeoutExpired(cmd, timeout, output="out", stderr="err")

    def fail_subprocess_run(*args, **kwargs):
        raise AssertionError("timeout builds must use process-tree runner")

    monkeypatch.setattr(
        debug_cli,
        "_run_with_process_group_timeout",
        fake_process_tree_runner,
        raising=False,
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fail_subprocess_run)

    result, retried = debug_cli._run_ninja_with_no_diag_retry(
        ["ninja", "build/GALE01/src/melee/mn/sample.o"],
        tmp_path,
        timeout=0.25,
    )

    assert calls == [
        (
            ["ninja", "build/GALE01/src/melee/mn/sample.o"],
            tmp_path,
            0.25,
        )
    ]
    assert result.returncode == 124
    assert retried is False
    assert "err" in result.stderr
    assert "timed out after 0.25s running ninja" in result.stderr


def test_debug_permute_triage_candidate_timeout_restores_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-284-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    real_call();\n}\n"
    )

    obj_cmd = ["ninja", "build/GALE01/src/melee/mn/sample.o"]
    calls: list[tuple[list[str], float | None]] = []

    def fake_ninja(cmd, melee_root_arg, *, timeout=None):
        cmd = [str(part) for part in cmd]
        calls.append((cmd, timeout))
        if cmd == obj_cmd:
            return (
                subprocess.CompletedProcess(
                    cmd,
                    124,
                    "",
                    "timed out after 0.01s running ninja sample.o",
                ),
                False,
            )
        return subprocess.CompletedProcess(cmd, 0, "", ""), False

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        lambda *args, **kwargs: pytest.fail("timed-out builds must not refresh"),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0.01",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "build-failed"
    assert "timed out after 0.01s" in data["results"][0]["first_diag"]
    assert src_path.read_text() == original
    assert calls[0] == (obj_cmd, 0.01)
    assert "output-284-1" in result.stderr
    assert "building build/GALE01/src/melee/mn/sample.o" in result.stderr
    status = json.loads(
        (output_dir / "melee-agent-candidate-status.json").read_text()
    )
    assert status["status"] == "build-failed"
    assert "timed out after 0.01s" in status["first_diag"]


def test_debug_permute_triage_rejects_unsafe_candidate_before_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1155-2"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    abs = (abs = -abs);\n}\n"
    )

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "unsafe-candidate"
    assert data["results"][0]["semantic_risk_bucket"] == "semantic-risk-high"
    assert data["results"][0]["source_risks"][0]["kind"] == (
        "repeated-scalar-assignment"
    )
    assert ["ninja", "build/GALE01/src/melee/mn/sample.o"] not in calls
    assert src_path.read_text() == original
    sidecar = output_dir / "melee-agent-candidate-status.json"
    sidecar_payload = json.loads(sidecar.read_text())
    assert sidecar_payload["status"] == "unsafe-candidate"
    assert sidecar_payload["semantic_risk_bucket"] == "semantic-risk-high"


def test_debug_permute_triage_rejects_scalar_self_assignment_source_risk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1155-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    abs = abs;\n    real_call();\n}\n"
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--json",
            "--threshold",
            "1.0",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "unsafe-candidate"
    assert data["results"][0]["semantic_risk_bucket"] == "semantic-risk-high"
    assert data["results"][0]["source_risks"][0]["severity"] == "reject"
    sidecar = output_dir / "melee-agent-candidate-status.json"
    status = json.loads(sidecar.read_text())
    assert status["status"] == "unsafe-candidate"
    assert status["semantic_risk_bucket"] == "semantic-risk-high"
    assert status["source_risks"][0]["kind"] == "scalar-self-assignment"


def test_debug_permute_triage_resume_skips_status_sidecars_before_max(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    old_dir = perm_dir / "output-1-1"
    old_dir.mkdir(parents=True)
    (old_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    old_call();\n}\n"
    )
    (old_dir / "melee-agent-candidate-status.json").write_text(json.dumps({
        "candidate": str(old_dir / "source.c"),
        "function": "fn_80000000",
        "semantic_risk_bucket": "repo-invalid",
        "source": "triage",
        "status": "build-failed",
    }))
    fresh_dir = perm_dir / "output-2-1"
    fresh_dir.mkdir()
    (fresh_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    fresh_call();\n}\n"
    )

    obj_cmd = ["ninja", "build/GALE01/src/melee/mn/sample.o"]
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    reads = iter([91.0, 91.25])
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: next(reads))
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--resume",
            "--max-candidates",
            "1",
            "--threshold",
            "1.0",
            "--candidate-timeout",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["skipped_count"] == 1
    assert data["skipped_candidates"][0]["path"] == str(old_dir / "source.c")
    assert data["skipped_candidates"][0]["semantic_risk_bucket"] == "repo-invalid"
    assert [Path(row["path"]).parent.name for row in data["results"]] == [
        "output-2-1"
    ]
    assert calls.count(obj_cmd) == 1


def test_debug_permute_triage_order_newest_applies_before_max(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    old_dir = perm_dir / "output-1-1"
    old_dir.mkdir(parents=True)
    (old_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    old_call();\n}\n"
    )
    fresh_dir = perm_dir / "output-2-1"
    fresh_dir.mkdir()
    (fresh_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    fresh_call();\n}\n"
    )
    os.utime(old_dir, (100, 100))
    os.utime(old_dir / "source.c", (100, 100))
    os.utime(fresh_dir, (200, 200))
    os.utime(fresh_dir / "source.c", (200, 200))

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    reads = iter([91.0, 91.25])
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: next(reads))
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--order",
            "newest",
            "--max-candidates",
            "1",
            "--threshold",
            "1.0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert [Path(row["path"]).parent.name for row in data["results"]] == [
        "output-2-1"
    ]


def test_debug_permute_verify_json_build_failure_reverts_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void)\n{\n    candidate_call();\n}\n")

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "ninja: error: build/GALE01/src/melee/mn/sample.d: "
                "FileNotFoundError\n"
            ),
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--candidate-timeout",
            "0",
        ],
    )

    assert result.exit_code == 4
    data = json.loads(result.stdout)
    assert data["status"] == "build-failed"
    assert data["source_reverted"] is True
    assert "FileNotFoundError" in data["first_diag"]
    assert src_path.read_text() == original


def test_debug_permute_verify_json_build_failure_writes_status_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    output_dir = tmp_path / "output-1190-1"
    output_dir.mkdir()
    candidate = output_dir / "source.c"
    candidate.write_text("void fn_80000000(void)\n{\n    abs = -abs;\n}\n")

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "FAILED: build/GALE01/src/melee/mn/sample.o\n"
                "#   File: src/melee/mn/sample.c\n"
                "#   Error: bad abs declaration\n"
            ),
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--candidate-timeout",
            "0",
        ],
    )

    assert result.exit_code == 4
    status = json.loads(
        (output_dir / "melee-agent-candidate-status.json").read_text()
    )
    assert status["status"] == "build-failed"
    assert "bad abs declaration" in status["first_diag"]
    assert src_path.read_text() == original


def test_debug_permute_verify_json_preserves_multiline_mwcc_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void)\n{\n    abs = -abs;\n}\n")

    mwcc_stderr = (
        "FAILED:  build/GALE01/src/melee/mn/sample.o\n"
        "#   File: src/melee/mn/sample.c\n"
        "#   Line: 27\n"
        "#   Code:     abs = -abs;\n"
        "#   Error:     ^^^\n"
        "#   undefined identifier 'abs'\n"
    )

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr=mwcc_stderr)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--candidate-timeout",
            "0",
        ],
    )

    assert result.exit_code == 4
    data = json.loads(result.stdout)
    assert data["status"] == "build-failed"
    assert "FAILED:" in data["first_diag"]
    assert "src/melee/mn/sample.c" in data["first_diag"]
    assert "abs = -abs;" in data["first_diag"]
    assert "undefined identifier 'abs'" in data["first_diag"]
    assert src_path.read_text() == original


def test_failure_diagnostic_preserves_context_after_file_line_error() -> None:
    stderr = (
        "FAILED: build/GALE01/src/melee/pl/plbonuslib.o\n"
        "src/melee/pl/plbonuslib.c:1172: error: undefined identifier 'f654_slot_helper'\n"
        "    f654_slot_helper(slot);\n"
        "    ^\n"
        "#   Error: illegal implicit declaration of function 'f654_slot_helper'\n"
    )

    diagnostic = debug_cli._failure_diagnostic_or_fallback(
        "",
        stderr,
        fallback="fallback",
    )

    assert "undefined identifier 'f654_slot_helper'" in diagnostic
    assert "f654_slot_helper(slot);" in diagnostic
    assert "^" in diagnostic
    assert "illegal implicit declaration" in diagnostic


def test_debug_permute_verify_json_retries_transient_report_json_decode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void)\n{\n    better_call();\n}\n")

    reads = iter([
        96.276474,
        json.JSONDecodeError("Unterminated string", "x", 0),
        96.49,
    ])

    def fake_get_match_pct(function, root):
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", fake_get_match_pct)
    monkeypatch.setattr(debug_cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--keep-failed",
            "--candidate-timeout",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["new_pct"] == 96.49
    assert data["improved"] is True
    assert src_path.read_text() == original


def test_debug_permute_verify_json_reports_persistent_report_json_decode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void)\n{\n    better_call();\n}\n")

    calls = {"match": 0}

    def fake_get_match_pct(function, root):
        calls["match"] += 1
        if calls["match"] == 1:
            return 96.276474
        raise json.JSONDecodeError("Unterminated string", "x", 0)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", fake_get_match_pct)
    monkeypatch.setattr(debug_cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "verify",
            str(candidate),
            "-f",
            "fn_80000000",
            "--json",
            "--candidate-timeout",
            "0",
        ],
    )

    assert result.exit_code == 5
    data = json.loads(result.stdout)
    assert data["status"] == "report-read-failed"
    assert "JSONDecodeError" in data["first_diag"]
    assert src_path.read_text() == original


def test_debug_permute_triage_rechecks_winners_before_ranking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1535-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    real_call();\n}\n"
    )

    pcts = iter([95.259926, 95.33213, 95.259926])

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: next(pcts))
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["best_path"] is None
    assert data["results"][0]["status"] == "nonreproducible"
    assert data["results"][0]["match_pct"] == 95.259926
    assert "recheck" in data["results"][0]["first_diag"]


def test_debug_permute_triage_json_preserves_multiline_mwcc_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    abs = -abs;\n}\n"
    )

    mwcc_stderr = (
        "FAILED:  build/GALE01/src/melee/mn/sample.o\n"
        "#   File: src/melee/mn/sample.c\n"
        "#   Line: 27\n"
        "#   Code:     abs = -abs;\n"
        "#   Error:     ^^^\n"
        "#   undefined identifier 'abs'\n"
    )

    def fake_run(cmd, **kwargs):
        if "build/GALE01/report.json" in [str(part) for part in cmd]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr=mwcc_stderr)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    first_diag = data["results"][0]["first_diag"]
    assert data["results"][0]["status"] == "build-failed"
    assert "FAILED:" in first_diag
    assert "src/melee/mn/sample.c" in first_diag
    assert "abs = -abs;" in first_diag
    assert "undefined identifier 'abs'" in first_diag
    assert src_path.read_text() == original


def test_debug_permute_triage_retries_transient_report_json_decode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n    real_call();\n}\n")
    objdiff = melee_root / "build" / "tools" / "objdiff-cli"
    objdiff.parent.mkdir(parents=True)
    objdiff.write_text("")

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    real_call();\n}\n"
    )

    reads = iter([
        91.0,
        json.JSONDecodeError("Unterminated string", "x", 0),
        91.01,
    ])

    def fake_get_match_pct(function, root):
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", fake_get_match_pct)
    monkeypatch.setattr(debug_cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "triage",
            str(perm_dir),
            "-f",
            "fn_80000000",
            "--candidate-timeout",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "ok"
    assert data["results"][0]["match_pct"] == 91.01


def test_refresh_match_pct_reports_persistent_report_json_decode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    objdiff = tmp_path / "build" / "tools" / "objdiff-cli"
    objdiff.parent.mkdir(parents=True)
    objdiff.write_text("")

    monkeypatch.setattr(debug_cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        debug_cli,
        "_get_match_pct",
        lambda function, root: (_ for _ in ()).throw(
            json.JSONDecodeError("Unterminated string", "x", 0)
        ),
    )

    pct, diagnostic = debug_cli._refresh_match_pct_after_successful_build(
        "melee/mn/sample",
        "fn_80000000",
        tmp_path,
    )

    assert pct is None
    assert diagnostic is not None
    assert "report.json" in diagnostic
    assert "JSON" in diagnostic


def test_dump_local_force_phys_help_describes_class_filtering() -> None:
    result = runner.invoke(app, ["debug", "dump", "local", "--help"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    normalized = " ".join(out.split())
    assert "Class-scoped entries are" in normalized
    assert "through to the DLL" in normalized
    assert "apply to that" in normalized
    assert "register class" in normalized
    assert "ignores the class prefix" not in normalized


def test_dump_local_help_exposes_force_frame_from_diff() -> None:
    result = runner.invoke(app, ["debug", "dump", "local", "--help"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "--force-frame-from-diff" in out
    assert "stack-frame immediates" in " ".join(out.split())

    alias_result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            "--force-no-home-from-diff",
            "--help",
        ],
    )
    assert alias_result.exit_code == 0


def test_dump_local_diff_holds_checkdiff_lock_while_staging_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    debug_compiler.write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000000\\n')\n"
        "obj = Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "obj.write_bytes(b'forced-object')\n"
    )
    wibo.chmod(0o755)
    build_o = melee_root / "build" / "GALE01" / "src" / "melee" / "mn" / "sample.o"
    build_o.parent.mkdir(parents=True)
    build_o.write_bytes(b"original-object")

    locked = False
    events: list[str] = []

    class FakeLock:
        def __enter__(self):
            nonlocal locked
            locked = True
            events.append("lock-enter")

        def __exit__(self, exc_type, exc, tb):
            nonlocal locked
            events.append("lock-exit")
            locked = False

    def fake_lock(root: Path):
        assert root == melee_root
        return FakeLock()

    def fake_run(cmd, **kwargs):
        nonlocal locked
        cmd_s = [str(part) for part in cmd]
        if cmd_s[:2] == ["python", "tools/checkdiff.py"]:
            assert locked is True
            assert kwargs["env"]["CHECKDIFF_NO_LOCK"] == "1"
            assert kwargs["env"]["CHECKDIFF_NO_FINGERPRINT"] == "1"
            assert build_o.read_bytes() == b"forced-object"
            events.append("checkdiff")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd_s}")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--diff",
            "--function",
            "fn_80000000",
            "--force-schedule",
            "lwz:0x94>0x90",
            "--force-schedule-fn",
            "fn_80000000",
            "--output",
            str(tmp_path / "pcdump.out"),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert events == ["lock-enter", "checkdiff", "lock-exit"]
    assert build_o.read_bytes() == b"original-object"


def test_dump_local_force_frame_from_diff_patches_before_final_checkdiff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug import force_frame as force_frame_mod

    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000000\\n')\n"
        "obj = Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "obj.write_bytes(b'compiled-object')\n"
    )
    wibo.chmod(0o755)
    build_o = melee_root / "build" / "GALE01" / "src" / "melee" / "mn" / "sample.o"
    build_o.parent.mkdir(parents=True)
    build_o.write_bytes(b"original-object")

    locked = False
    events: list[str] = []

    class FakeLock:
        def __enter__(self):
            nonlocal locked
            locked = True
            events.append("lock-enter")

        def __exit__(self, exc_type, exc, tb):
            nonlocal locked
            events.append("lock-exit")
            locked = False

    def fake_run(cmd, **kwargs):
        nonlocal locked
        cmd_s = [str(part) for part in cmd]
        if cmd_s[:2] != ["python", "tools/checkdiff.py"]:
            raise AssertionError(f"unexpected command: {cmd_s}")
        assert locked is True
        assert kwargs["env"]["CHECKDIFF_NO_LOCK"] == "1"
        assert kwargs["env"]["CHECKDIFF_NO_FINGERPRINT"] == "1"
        if "--format" in cmd_s and cmd_s[cmd_s.index("--format") + 1] == "json":
            assert kwargs["capture_output"] is True
            assert kwargs["text"] is True
            assert build_o.read_bytes() == b"compiled-object"
            events.append("json-checkdiff")
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps({"target_asm": [], "current_asm": []}),
                stderr="",
            )
        assert build_o.read_bytes() == b"patched-object"
        events.append("plain-checkdiff")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_derive(payload):
        events.append("derive-plan")
        return SimpleNamespace(is_empty=False)

    def fake_apply(path, function, plan):
        assert path == build_o
        assert function == "fn_80000000"
        events.append("apply-plan")
        path.write_bytes(b"patched-object")
        return SimpleNamespace(
            byte_patches_applied=2,
            symbol_renames=[("@146", "gm_804DAAB0")],
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", lambda root: FakeLock())
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(force_frame_mod, "derive_force_frame_patch_plan", fake_derive)
    monkeypatch.setattr(force_frame_mod, "apply_force_frame_patch_plan", fake_apply)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--diff",
            "--force-frame-from-diff",
            "--function",
            "fn_80000000",
            "--output",
            str(tmp_path / "pcdump.out"),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert events == [
        "lock-enter",
        "json-checkdiff",
        "derive-plan",
        "apply-plan",
        "plain-checkdiff",
        "lock-exit",
    ]
    assert build_o.read_bytes() == b"original-object"


def test_dump_local_diff_missing_object_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000000\\n')\n"
    )
    wibo.chmod(0o755)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--diff",
            "--function",
            "fn_80000000",
            "--output",
            str(tmp_path / "pcdump.out"),
            "--no-cache-sync",
        ],
    )

    assert result.exit_code == 4
    assert "--diff requested but .o not produced" in result.stderr
    assert (tmp_path / "pcdump.out").exists()


def test_dump_local_requested_function_missing_exits_nonzero_and_preserves_dump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text('Starting function fn_80000001\\n')\n"
    )
    wibo.chmod(0o755)
    output = tmp_path / "pcdump.out"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--function",
            "fn_80000000",
            "--output",
            str(output),
            "--no-cache-sync",
        ],
    )

    assert result.exit_code == 3
    assert "function 'fn_80000000' not found in pcdump" in result.stderr
    assert "fn_80000001" in result.stderr
    assert output.exists()
    assert "Starting function fn_80000001" in output.read_text()


def test_dump_local_watchdog_uses_process_tree_killer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(10)\n"
    )
    wibo.chmod(0o755)
    killed: list[int] = []

    def fake_kill_tree(proc_handle: subprocess.Popen[str]) -> None:
        killed.append(proc_handle.pid)
        os.killpg(os.getpgid(proc_handle.pid), 9)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setattr(debug_cli, "_kill_debug_dump_local_process_tree", fake_kill_tree)
    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "0.1")

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--function",
            "fn_80000000",
            "--output",
            str(tmp_path / "pcdump.out"),
            "--no-cache-sync",
        ],
    )

    assert result.exit_code == 124
    assert killed
    assert "no compile progress" in result.stderr


def test_dump_local_watchdog_treats_pcdump_growth_as_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "with pcdump.open('w') as f:\n"
        "    for i in range(8):\n"
        "        f.write('Starting function fn_80000000\\n')\n"
        "        f.write(f'chunk {i}\\n')\n"
        "        f.flush()\n"
        "        time.sleep(0.2)\n"
    )
    wibo.chmod(0o755)
    killed: list[int] = []

    def fake_kill_tree(proc_handle: subprocess.Popen[str]) -> None:
        killed.append(proc_handle.pid)
        os.killpg(os.getpgid(proc_handle.pid), 9)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setattr(debug_cli, "_kill_debug_dump_local_process_tree", fake_kill_tree)
    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "0.1")
    output = tmp_path / "pcdump.out"

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--function",
            "fn_80000000",
            "--output",
            str(output),
            "--no-cache-sync",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert killed == []
    assert "no compile progress" not in result.stderr
    assert output.exists()
    assert "chunk 7" in output.read_text()


def test_inspect_explain_schedule_reads_pcdump(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(
        "Starting function fn_80000000\n"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        "    lwz     r6,144(r31)\n"
        "    lwz     r7,148(r31)\n"
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-schedule",
            "--function",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--force-schedule",
            "lwz:0x94>0x90",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "explain-schedule - fn_80000000" in result.stdout
    assert "heuristic_verdict=PRIORITY_UNAVAILABLE" in result.stdout
    assert "window_gap=0" in result.stdout
    assert "priority data unavailable" in result.stdout
    assert "small source-order nudges" not in result.stdout


def test_inspect_explain_schedule_json_reads_pcdump(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(
        "Starting function fn_80000000\n"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        "    lwz     r6,144(r31)\n"
        "    addi    r9,r31,8\n"
        "    lwz     r7,148(r31)\n"
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-schedule",
            "--function",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--force-schedule",
            "lwz:0x94>0x90",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    decision = payload["decisions"][0]
    assert decision["heuristic_verdict"] == "PRIORITY_UNAVAILABLE"
    assert decision["window_gap"] == 1


def test_inspect_explain_schedule_source_file_adds_provenance(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(
        "Starting function fn_80000000\n"
        "AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        "    lwz     r40,148(r32)\n"
        "    lwz     r41,144(r32)\n"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        "    lwz     r7,148(r31)\n"
        "    lwz     r6,144(r31)\n"
    )
    source = tmp_path / "source.c"
    source.write_text(
        "typedef struct Obj Obj;\n"
        "void fn_80000000(Obj* obj) {\n"
        "    int hi = obj->x94;\n"
        "    int lo = obj->x90;\n"
        "    sink(hi, lo);\n"
        "}\n"
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-schedule",
            "--function",
            "fn_80000000",
            "--pcdump",
            str(pcdump),
            "--source-file",
            str(source),
            "--force-schedule",
            "lwz:0x94>0x90",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "ir=B0:0" in result.stdout
    assert f"source={source}:3:13" in result.stdout
    assert "expr=obj->x94" in result.stdout


def test_debug_diff_schedule_reports_first_divergence(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real-pcdump.txt"
    forced = tmp_path / "forced-pcdump.txt"
    pre = (
        "Starting function fn_80000000\n"
        "AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        "    lwz     r40,148(r32)\n"
        "    lwz     r41,144(r32)\n"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "fn_80000000\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
    )
    real.write_text(pre + "    lwz     r6,144(r31)\n    lwz     r7,148(r31)\n")
    forced.write_text(pre + "    lwz     r7,148(r31)\n    lwz     r6,144(r31)\n")
    source = tmp_path / "source.c"
    source.write_text(
        "typedef struct Obj Obj;\n"
        "void fn_80000000(Obj* obj) {\n"
        "    int hi = obj->x94;\n"
        "    int lo = obj->x90;\n"
        "    sink(hi, lo);\n"
        "}\n"
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "diff-schedule",
            "--function",
            "fn_80000000",
            "--pcdump",
            str(real),
            "--against",
            str(forced),
            "--source-file",
            str(source),
            "--force-schedule",
            "lwz:0x94>0x90",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "first divergence: step=1 rule=lwz:0x94>0x90" in result.stdout
    assert "real picked observed-first" in result.stdout
    assert "forced picked target-first" in result.stdout
    assert "margin=priority data unavailable" in result.stdout
    assert "expr=obj->x94" in result.stdout


def test_debug_dump_doctor_reports_missing_debug_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc.exe").write_text("")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    (tools_dir / "MWDBG326.dll").write_text("")
    (tools_dir / "build_wibo.sh").write_text("")
    (tools_dir / "build_macos.sh").write_text("")
    (tools_dir / "patch_mwcceppc_for_wibo.py").write_text("")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: None)

    result = runner.invoke(app, ["debug", "dump", "doctor"])

    assert result.exit_code == 2
    out = strip_ansi(result.stdout)
    assert "FAIL\twibo" in out
    assert "FAIL\tpatched compiler" in out
    assert "melee-agent debug dump setup" in out


def test_debug_dump_doctor_passes_ready_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    for filename in ("mwcceppc.exe", "mwcceppc_debug.exe", "MWDBG326.dll"):
        (compiler_dir / filename).write_text("")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    for filename in (
        "MWDBG326.dll",
        "build_wibo.sh",
        "build_macos.sh",
        "mwcc_debug.c",
        "patch_mwcceppc_for_wibo.py",
    ):
        (tools_dir / filename).write_text("")
    ready_time = 1_000_000_000
    os.utime(tools_dir / "mwcc_debug.c", (ready_time, ready_time))
    for dll in (tools_dir / "MWDBG326.dll", compiler_dir / "MWDBG326.dll"):
        os.utime(dll, (ready_time, ready_time))
    wibo = tmp_path / "tools" / "mwcc_debug" / "bin" / "wibo"
    wibo.parent.mkdir(parents=True)
    wibo.write_text("")
    wibo.chmod(0o755)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)

    result = runner.invoke(app, ["debug", "dump", "doctor"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "PASS\twibo" in out
    assert "PASS\tpatched compiler" in out
    assert "ready for `melee-agent debug dump local`" in out


def test_debug_dump_doctor_reports_stale_dll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    for filename in ("mwcceppc.exe", "mwcceppc_debug.exe", "MWDBG326.dll"):
        (compiler_dir / filename).write_text("")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    for filename in (
        "MWDBG326.dll",
        "build_wibo.sh",
        "build_macos.sh",
        "patch_mwcceppc_for_wibo.py",
    ):
        (tools_dir / filename).write_text("")
    source = tools_dir / "mwcc_debug.c"
    source.write_text("// newer source")
    stale_time = 1_000_000_000
    fresh_time = stale_time + 10
    for path in (tools_dir / "MWDBG326.dll", compiler_dir / "MWDBG326.dll"):
        path.write_text("old dll")
        path.chmod(0o755)
        os.utime(path, (stale_time, stale_time))
    os.utime(source, (fresh_time, fresh_time))
    wibo = tmp_path / "tools" / "mwcc_debug" / "bin" / "wibo"
    wibo.parent.mkdir(parents=True)
    wibo.write_text("")
    wibo.chmod(0o755)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)

    result = runner.invoke(app, ["debug", "dump", "doctor"])

    assert result.exit_code == 2
    out = strip_ansi(result.stdout)
    assert "FAIL\tmwcc_debug DLL freshness" in out
    assert "newer than DLL" in out
    assert "melee-agent debug dump setup" in out


def test_debug_dump_setup_rebuilds_stale_dll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    for filename in ("mwcceppc.exe", "mwcceppc_debug.exe"):
        (compiler_dir / filename).write_text("")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    dll = tools_dir / "MWDBG326.dll"
    source = tools_dir / "mwcc_debug.c"
    dll.write_text("old dll")
    source.write_text("// newer source")
    for filename in ("build_wibo.sh", "build_macos.sh", "patch_mwcceppc_for_wibo.py"):
        (tools_dir / filename).write_text("")
    wibo = tools_dir / "bin" / "wibo"
    wibo.parent.mkdir(parents=True)
    wibo.write_text("")
    wibo.chmod(0o755)
    os.utime(dll, (1_000_000_000, 1_000_000_000))
    os.utime(source, (1_000_000_010, 1_000_000_010))

    build_calls = 0

    def fake_build() -> Path:
        nonlocal build_calls
        build_calls += 1
        dll.write_text("new dll")
        os.utime(dll, (1_000_000_020, 1_000_000_020))
        return dll

    patch_calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> SimpleNamespace:
        patch_calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_build_local_dll", fake_build)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(app, ["debug", "dump", "setup"])

    assert result.exit_code == 0
    assert build_calls == 1
    assert patch_calls
    assert str(dll) in patch_calls[0]
    out = strip_ansi(result.stdout)
    assert "building mwcc_debug DLL" in out


def test_debug_dump_setup_promotes_import_name_dll_when_build_omits_mwdbg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc.exe").write_text("stock compiler")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    source = tools_dir / "mwcc_debug.c"
    source.write_text("// source")
    for filename in ("build_wibo.sh", "build_macos.sh", "patch_mwcceppc_for_wibo.py"):
        (tools_dir / filename).write_text("")
    wibo = tools_dir / "bin" / "wibo"
    wibo.parent.mkdir(parents=True)
    wibo.write_text("")
    wibo.chmod(0o755)

    patch_calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs) -> SimpleNamespace:
        if args and str(args[0]).endswith("build_macos.sh"):
            (tools_dir / "lmgr326b.dll").write_text("built dll")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        patch_calls.append(args)
        dll_arg = Path(args[args.index("--dll") + 1])
        (compiler_dir / "MWDBG326.dll").write_bytes(dll_arg.read_bytes())
        (compiler_dir / "mwcceppc_debug.exe").write_text("patched compiler")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(app, ["debug", "dump", "setup"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (tools_dir / "MWDBG326.dll").read_text() == "built dll"
    assert patch_calls
    assert str(tools_dir / "MWDBG326.dll") in patch_calls[0]
    out = strip_ansi(result.stdout)
    assert "using alternate DLL output" in out


def test_debug_dump_local_probe_uses_same_tu_build_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "melee" / "ft" / "ftdynamics.c"
    source.parent.mkdir(parents=True)
    source.write_text("void ftCo_8009E7B4(void) {}\n")
    probe = tmp_path / "build" / "mwcc_debug_cache" / "probes" / "e7b4" / "probe.c"
    probe.parent.mkdir(parents=True)
    probe.write_text("void ftCo_8009E7B4(void) {}\n")
    output = tmp_path / "probe.pcdump.txt"
    args_file = tmp_path / "wibo-args.txt"

    (tmp_path / "build.ninja").write_text(textwrap.dedent("""\
        build build/GALE01/src/melee/ft/ftdynamics.o: mwcc src/melee/ft/ftdynamics.c
          cflags = -I include -DREAL_TU_FLAG=1
          mw_version = GC/1.2.5n
    """))
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("debug compiler")

    wibo = tmp_path / "fake-wibo.py"
    wibo.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import os
        import pathlib
        import sys

        pathlib.Path(os.environ["MELEE_TEST_WIBO_ARGS"]).write_text(
            "\\n".join(sys.argv[1:]),
            encoding="utf-8",
        )
        pcdump_path = pathlib.Path(os.environ["MWCC_DEBUG_PCDUMP_PATH"])
        pcdump_path.write_text(
            "Starting function ftCo_8009E7B4\\n"
            "AFTER REGISTER COLORING\\n"
            "ftCo_8009E7B4\\n"
            "B0: Succ={} Pred={} Labels={}\\n"
            "    blr\\n",
            encoding="utf-8",
        )
        if "-o" in sys.argv:
            pathlib.Path(sys.argv[sys.argv.index("-o") + 1]).write_text(
                "object",
                encoding="utf-8",
            )
    """))
    wibo.chmod(0o755)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setenv("MELEE_TEST_WIBO_ARGS", str(args_file))

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(probe),
            "--unit-source",
            str(source),
            "--function",
            "ftCo_8009E7B4",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert output.exists()
    args_text = args_file.read_text()
    assert "-DREAL_TU_FLAG=1" in args_text
    assert "src/melee/ft" in args_text
    assert "build/mwcc_debug_cache/probes/e7b4/probe.c" in args_text
    assert "src/melee/ft/ftdynamics.c" not in args_text
    assert "same-TU probe" in result.stderr


def test_force_coalesce_preflight_rejects_known_unsafe_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text("pcdump")
    src = tmp_path / "src" / "melee" / "mn" / "sample.c"
    src.parent.mkdir(parents=True)
    src.write_text("void fn_80000000(void) {}\n")

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda *args, **kwargs: pcdump)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(
        debug_cli,
        "_force_coalesce_preflight_report",
        lambda **kwargs: SimpleNamespace(
            pairs=[
                SimpleNamespace(
                    preflight=SimpleNamespace(
                        safe=False,
                        reasons=["virtuals interfere directly per colorgraph data"],
                    )
                )
            ]
        ),
    )

    with pytest.raises(typer.Exit) as exc:
        debug_cli._reject_unsafe_force_coalesce(
            force_coalesce="39=40",
            function="fn_80000000",
            melee_root=tmp_path,
        )

    assert exc.value.exit_code == 2


def test_force_coalesce_preflight_requires_fresh_cached_pcdump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "src" / "melee" / "ty" / "tylist.c"
    src.parent.mkdir(parents=True)
    src.write_text("void un_803147C4(void) {}\n")

    def missing_fresh_pcdump(*args, **kwargs):
        raise typer.Exit(4)

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", missing_fresh_pcdump)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/ty/tylist",
    )

    with pytest.raises(typer.Exit) as exc:
        debug_cli._reject_unsafe_force_coalesce(
            force_coalesce="36=39",
            function="un_803147C4",
            melee_root=tmp_path,
        )

    assert exc.value.exit_code == 2
    assert "fresh cached pcdump required" in capsys.readouterr().err


def test_force_coalesce_preflight_skips_self_uncoalesce_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text("pcdump")

    called = False

    def fail_preflight(**kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(pairs=[])

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda *args, **kwargs: pcdump)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: None)
    monkeypatch.setattr(debug_cli, "_force_coalesce_preflight_report", fail_preflight)

    debug_cli._reject_unsafe_force_coalesce(
        force_coalesce="43=43",
        function="fn_80000000",
        melee_root=tmp_path,
    )
    assert called is False


def test_force_coalesce_hook_normalizes_alias_roots_before_override() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    hook_source = repo_root / "tools" / "mwcc_debug" / "mwcc_debug.c"
    text = hook_source.read_text()

    assert "coalesce_find_root_guarded" in text
    assert "detected alias cycle" in text
    assert "alias[v] = (int16)target_root" in text
    assert "alias[v] = (int16)r;" not in text


def test_mutate_type_change_diff_prints_focused_preview(monkeypatch, tmp_path) -> None:
    src_path = tmp_path / "sample.c"
    source = "void f(void)\n{\n    int x;\n    x = 1;\n}\n"
    src_path.write_text(source)
    monkeypatch.setattr(debug_cli, "_read_source_for", lambda function, root: (src_path, source))

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "type-change",
            "-f",
            "f",
            "--var",
            "x",
            "--type",
            "u32",
            "--diff",
        ],
    )

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "--- " in out
    assert "+++ " in out
    assert "-    int x;" in out
    assert "+    u32 x;" in out
    assert src_path.read_text() == source


def test_mutate_type_change_accepts_source_file_override(tmp_path) -> None:
    src_path = tmp_path / "dirty.c"
    source = "void f(void)\n{\n    int flag;\n    flag = 1;\n}\n"
    src_path.write_text(source)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "type-change",
            "-f",
            "f",
            "--var",
            "flag",
            "--type",
            "u32",
            "--source-file",
            str(src_path),
            "--diff",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "-    int flag;" in out
    assert "+    u32 flag;" in out
    assert src_path.read_text() == source


def test_decl_orders_json_keep_best_applies_winner_and_refreshes_baseline(monkeypatch, tmp_path) -> None:
    melee_root = tmp_path
    report_dir = melee_root / "build" / "GALE01"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/mn/sample",
                        "functions": [
                            {"name": "f", "fuzzy_match_percent": 10.0},
                        ],
                    }
                ]
            }
        )
    )
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void f(void)\n{\n    int a;\n    int b;\n    a = b;\n}\n"
    src_path.write_text(original)

    seen_texts: list[str] = []

    def fake_build_and_match(unit, function, root, *, fast_report=True):
        assert unit == "melee/mn/sample"
        assert function == "f"
        assert root == melee_root
        text = src_path.read_text()
        seen_texts.append(text)
        if "int b;\n    int a;" in text:
            return 20.0
        return 12.5

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_build_and_match", fake_build_and_match)
    monkeypatch.setattr(debug_cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "decl-orders",
            "f",
            "--strategy",
            "swap",
            "--threshold",
            "1",
            "--keep-best",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["baseline_pct"] == 12.5
    assert data["best_pct"] == 20.0
    assert data["best_label"] == "swap a <-> b"
    assert "int b;\n    int a;" in src_path.read_text()
    assert seen_texts[0] == original


def test_decl_orders_json_emits_candidate_progress_to_stderr(monkeypatch, tmp_path) -> None:
    melee_root = tmp_path
    report_dir = melee_root / "build" / "GALE01"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/mn/sample",
                        "functions": [
                            {"name": "f", "fuzzy_match_percent": 10.0},
                        ],
                    }
                ]
            }
        )
    )
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void f(void)\n{\n    int a;\n    int b;\n    a = b;\n}\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_build_and_match", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(debug_cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "decl-orders",
            "f",
            "--strategy",
            "swap",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["function"] == "f"
    assert "[decl-orders] 1/1 swap a <-> b" in strip_ansi(result.stderr)


def test_decl_orders_auto_selects_nested_scope_when_top_has_no_decls(
    monkeypatch,
    tmp_path,
) -> None:
    melee_root = tmp_path
    report_dir = melee_root / "build" / "GALE01"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/mn/sample",
                        "functions": [
                            {"name": "f", "fuzzy_match_percent": 10.0},
                        ],
                    }
                ]
            }
        )
    )
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = textwrap.dedent("""\
        void f(int flag)
        {
            if (flag) {
                int a;
                int b;
                a = b;
            }
        }
    """)
    src_path.write_text(original)

    def fake_build_and_match(unit, function, root, *, fast_report=True):
        text = src_path.read_text()
        if "int b;\n        int a;" in text:
            return 20.0
        return 10.0

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_build_and_match", fake_build_and_match)
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "decl-orders",
            "f",
            "--strategy",
            "swap",
            "--threshold",
            "1",
            "--keep-best",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["scope"].startswith("f/block@")
    assert payload["selected_scope_reason"] == "auto-nested"
    assert payload["available_scopes"][0]["scope"] == payload["scope"]
    assert payload["available_scopes"][0]["names"] == ["a", "b"]
    assert payload["best_label"] == "swap a <-> b"
    assert "int b;\n        int a;" in src_path.read_text()


def test_diagnose_decl_orders_uses_scope_map_for_struct_initializer_decls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "ft" / "ft_0852.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(textwrap.dedent("""\
        void ft_800852B0(void)
        {
            struct UnkCostumeList* var_r8 = CostumeListsForeachCharacter;
            ftData_UnkCountStruct* var_r9 = ftData_Table_Unk0;
            ftData_UnkCountStruct* var_r10 = ftData_UnkIntPairs;
            int i;

            for (i = 0; i < FTKIND_MAX; ++var_r8, ++var_r9, ++var_r10, ++i) {
                int costume_idx = 0;
                gFtDataList[i] = NULL;
            }
        }
    """))
    pcdump = tmp_path / "ft_800852B0.pcdump.txt"
    pcdump.write_text("Starting function ft_800852B0\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/ft/ft_0852",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 97.36)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    def fake_build_and_match_with_diagnostic(unit, function, root, *, timeout=60.0):
        text = src_path.read_text()
        if "var_r9 = ftData_Table_Unk0;\n    struct UnkCostumeList* var_r8" in text:
            return 97.40, None
        return 97.36, None

    monkeypatch.setattr(
        debug_cli,
        "_build_and_match_with_diagnostic",
        fake_build_and_match_with_diagnostic,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "ft_800852B0",
            "--decl-strategy",
            "swap",
            "--max-seconds",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "Could not find decl block" not in out
    assert "Scope: ft_800852B0 (function-top)" in out
    assert "swap var_r8<->var_r9" in out
    assert "WIN: swap var_r8<->var_r9" in out
    assert src_path.read_text().startswith("void ft_800852B0")


def test_suggest_register_tiebreak_emits_compiler_temp_levers() -> None:
    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "register-tiebreak",
            "-f",
            "ft_800852B0",
            "--force-phys",
            "53:4",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "Register-tiebreak source levers for ft_800852B0" in out
    assert "ig53 -> r4" in out
    assert "occupy r3" in out
    assert "move the defining expression" in out
    assert "debug inspect virtual-to-var -f ft_800852B0 r53" in out
    assert (
        "debug mutate simplify-order --fn ft_800852B0 "
        "--force-phys 53:4 --no-preserve-precolor"
    ) in out
    assert "--want-late 53" not in out


def test_suggest_register_tiebreak_json_is_structured() -> None:
    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "register-tiebreak",
            "-f",
            "ft_800852B0",
            "--force-phys",
            "0:53:4",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["function"] == "ft_800852B0"
    assert payload["normalized_force_phys"] == "0:53:4"
    assert payload["targets"][0]["ig_idx"] == 53
    assert payload["targets"][0]["target_phys"] == 4
    assert any(
        lever["kind"] == "interference-insertion"
        for lever in payload["levers"]
    )


def test_mutate_simplify_order_emits_candidate_progress_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture_mod
    import src.mwcc_debug.simplify_search as simplify_search_mod

    melee_root = tmp_path
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) {}\n")

    section = SimpleNamespace(class_id=0)
    base_events = SimpleNamespace(
        name="fn_80000000",
        colorgraph_sections=[section],
        simplify_sections=[section],
        coalesce_sections=[],
    )
    baseline_sig = SimpleNamespace(simplify_order=(41, 40))

    def fake_search(*, progress_callback=None, max_candidates=100, **kwargs):
        if progress_callback is not None:
            progress_callback(1, max_candidates, "decl-orders swap a <-> b")
        return SimpleNamespace(
            exact_match=None,
            progress=[],
            gate_rejected_count=0,
            gate_rejection_reasons=[],
            rejected_scored=[],
            compile_failure_count=0,
            total_compiles=1,
            elapsed_seconds=300.0,
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        diff_capture_mod,
        "compile_source_variant",
        lambda *args, **kwargs: "pcdump",
    )
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda text: [base_events])
    monkeypatch.setattr(
        simplify_search_mod,
        "baseline_signature",
        lambda events, *, class_id: baseline_sig,
    )
    monkeypatch.setattr(simplify_search_mod, "search", fake_search)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "simplify-order",
            "-f",
            "fn_80000000",
            "--want-late",
            "40",
            "--max-candidates",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert (
        "[simplify-order] compiling 1/1: decl-orders swap a <-> b"
        in strip_ansi(result.stderr)
    )
    assert "Compiled:        1 variant(s)" in strip_ansi(result.stdout)


def test_suggest_coalesce_requires_fresh_cached_pcdump(monkeypatch) -> None:
    def fake_resolve(pcdump, function, melee_root=None, *, require_fresh=False):
        assert require_fresh is True
        raise typer.Exit(4)

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fake_resolve)

    result = runner.invoke(
        app,
        ["debug", "suggest", "coalesce", "-f", "fn_80000000", "--discover"],
    )

    assert result.exit_code == 4


def test_ceiling_requires_fresh_cached_pcdump_before_verdict(monkeypatch, tmp_path: Path) -> None:
    melee_root = tmp_path
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) {}\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 91.0)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])

    def fake_resolve(pcdump, function, melee_root=None, *, require_fresh=False):
        assert require_fresh is True
        raise typer.Exit(4)

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fake_resolve)

    result = runner.invoke(
        app,
        ["debug", "inspect", "ceiling", "fn_80000000", "--skip-decl-orders"],
    )

    assert result.exit_code == 4
    assert "PROBABLE CEILING" not in strip_ansi(result.stdout)


def test_inspect_stuck_suppresses_decl_orders_when_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    report_dir = melee_root / "build" / "GALE01"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "units": [
                    {
                        "name": "main/melee/mn/sample",
                        "functions": [
                            {
                                "name": "fn_80000000",
                                "fuzzy_match_percent": 99.45,
                            },
                        ],
                    }
                ]
            }
        )
    )
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(void)\n{\n    int only;\n    only = 0;\n}\n"
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])

    result = runner.invoke(
        app,
        ["debug", "inspect", "stuck", "fn_80000000", "--no-pcdump", "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    next_steps = "\n".join(payload["next_steps"])
    assert "debug mutate decl-orders fn_80000000" not in next_steps
    assert "no decl-order candidates" in next_steps
    assert "debug inspect diagnose fn_80000000 --skip-decl-orders" in next_steps


def test_inspect_stuck_routes_frame_size_rows_to_frame_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    int a;\n"
        "    int b;\n"
        "    a = 0;\n"
        "    b = a;\n"
        "}\n"
    )

    def fake_run(cmd, **kwargs):
        cmd_s = [str(part) for part in cmd]
        assert cmd_s[:2] == ["python", "tools/checkdiff.py"]
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "classification": {
                        "primary": "stack-layout",
                        "reasons": [
                            "frame reservation gap is too large; try PAD_STACK"
                        ],
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 99.45)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        ["debug", "inspect", "stuck", "fn_80000000", "--no-pcdump", "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame_residual"]["kind"] == "frame-size"
    assert payload["frame_residual"]["subcategory"] == "frame-too-large"
    assert payload["next_steps"][0] == (
        "melee-agent debug inspect frame-reservations -f fn_80000000"
    )
    assert "debug suggest frame -f fn_80000000" in payload["next_steps"][1]
    joined = "\n".join(payload["next_steps"][:3])
    assert "debug mutate decl-orders fn_80000000" not in joined
    assert "Optional cheap probe" in "\n".join(payload["next_steps"])


def test_inspect_stuck_routes_same_slot_rows_to_lifetime_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(void)\n"
        "{\n"
        "    int a;\n"
        "    int b;\n"
        "    a = 0;\n"
        "    b = a;\n"
        "}\n"
    )

    def fake_run(cmd, **kwargs):
        cmd_s = [str(part) for part in cmd]
        assert cmd_s[:2] == ["python", "tools/checkdiff.py"]
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "classification": {
                        "primary": "stack-slot-layout",
                        "reasons": [
                            "2 differing paired lines reference stack slots"
                        ],
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 99.45)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        ["debug", "inspect", "stuck", "fn_80000000", "--no-pcdump", "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame_residual"]["kind"] == "same-frame-stack-slot-placement"
    assert payload["next_steps"][0] == (
        "melee-agent debug inspect frame-reservations -f fn_80000000"
    )
    assert payload["next_steps"][1] == (
        "melee-agent debug mutate lifetime-layout -f fn_80000000 --compile-probes"
    )
    assert "stack-home assignment order" in payload["frame_residual"]["message"]
    assert "Optional cheap probe" in "\n".join(payload["next_steps"])


def test_tier3_search_no_improvement_is_successful_search_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) { int x; x = 1; }\n")
    pcdump_path = tmp_path / "pcdump.txt"
    pcdump_path.write_text("pcdump fixture")
    target_path = tmp_path / "target.json"
    target_path.write_text("{}")

    perm_root = tmp_path / "permuter"
    perm_dir = perm_root / "nonmatchings" / "fn_80000000"
    perm_dir.mkdir(parents=True)
    for name in ("target.o", "settings.toml"):
        (perm_dir / name).write_text("")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\n")

    wibo = tmp_path / "wibo"
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    wibo.write_text("")
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("")

    pre = object()
    parsed_fn = SimpleNamespace(name="fn_80000000", last_precolor_pass=lambda: pre)
    plan = tier3_mod.SeedPlan(
        mutator="type-change",
        target_var="x",
        args={"new_type": "long"},
        description="type-change x: int -> long",
    )
    compile_result = tier3_mod.CompileResult(
        ok=True,
        stderr="",
        stdout="",
        one_line_reason="",
    )
    no_win = tier3_mod.PerSeedPermuteResult(
        seed_idx=0,
        plan=plan,
        seed_dir=perm_dir / "tier3_seed_0",
        best_candidate=None,
        best_score=None,
        baseline_score=100,
        delta=0,
        ran_seconds=0.0,
    )

    import src.mwcc_debug.symbol_bridge as symbol_bridge

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda path, function, root=None: pcdump_path)
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [parsed_fn])
    monkeypatch.setattr(symbol_bridge, "list_bindings", lambda source, function, pass_obj: [object()])
    monkeypatch.setattr(tier3_mod, "plan_seeds", lambda bindings, budget, include_low_confidence: [plan])
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    def fake_materialize_seed(source, fn, seed_plan, seed_dir):
        seed_dir.mkdir(parents=True)
        out = seed_dir / "base.c"
        out.write_text(source)
        return out

    monkeypatch.setattr(tier3_mod, "materialize_seed", fake_materialize_seed)
    monkeypatch.setattr(tier3_mod, "smoke_compile", lambda *args, **kwargs: compile_result)
    monkeypatch.setattr(tier3_mod, "run_per_seed_permute", lambda **kwargs: no_win)
    monkeypatch.setattr(tier3_mod, "rank_seed_results", lambda results: results)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "search",
            "-f",
            "fn_80000000",
            "--budget",
            "1",
            "--per-seed-time",
            "1",
            "--total-time",
            "1",
            "--perm-root",
            str(perm_root),
            "--target",
            str(target_path),
        ],
    )

    assert result.exit_code == 0
    assert "No seed produced a permuter improvement" in strip_ansi(result.stderr)


def test_tier3_search_falls_back_to_source_shape_probe_seeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe

    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    base_source = "void fn_80000000(void) { int x; x = 1; }\n"
    patched_source = "void fn_80000000(void) { int x; int cursor; x = 1; }\n"
    src_path.write_text(base_source)
    pcdump_path = tmp_path / "pcdump.txt"
    pcdump_path.write_text("pcdump fixture")
    target_path = tmp_path / "target.json"
    target_path.write_text("{}")

    perm_root = tmp_path / "permuter"
    perm_dir = perm_root / "nonmatchings" / "fn_80000000"
    perm_dir.mkdir(parents=True)
    for name in ("target.o", "settings.toml"):
        (perm_dir / name).write_text("")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\n")

    wibo = tmp_path / "wibo"
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    wibo.write_text("")
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("")

    pre = object()
    parsed_fn = SimpleNamespace(name="fn_80000000", last_precolor_pass=lambda: pre)
    compile_result = tier3_mod.CompileResult(
        ok=True,
        stderr="",
        stdout="",
        one_line_reason="",
    )

    import src.mwcc_debug.pressure_explorer as pressure_explorer
    import src.mwcc_debug.symbol_bridge as symbol_bridge

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda path, function, root=None: pcdump_path)
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [parsed_fn])
    monkeypatch.setattr(symbol_bridge, "list_bindings", lambda source, function, pass_obj: [])
    monkeypatch.setattr(tier3_mod, "plan_seeds", lambda bindings, budget, include_low_confidence: [])
    monkeypatch.setattr(
        pressure_explorer,
        "generate_lifetime_layout_probes",
        lambda source, function, max_probes=12: [
            LifetimeLayoutProbe(
                label="case-c2-loop-cursor",
                operator="temp-introduction",
                description="rebind loop cursor temp",
                source_text=patched_source,
            )
        ],
    )
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(tier3_mod, "smoke_compile", lambda *args, **kwargs: compile_result)

    def fake_run_per_seed_permute(**kwargs):
        return tier3_mod.PerSeedPermuteResult(
            seed_idx=kwargs["seed_idx"],
            plan=kwargs["plan"],
            seed_dir=kwargs["seed_dir"],
            best_candidate=None,
            best_score=None,
            baseline_score=None,
            delta=0,
            ran_seconds=0.0,
        )

    monkeypatch.setattr(tier3_mod, "run_per_seed_permute", fake_run_per_seed_permute)
    monkeypatch.setattr(tier3_mod, "rank_seed_results", lambda results: results)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "search",
            "-f",
            "fn_80000000",
            "--budget",
            "1",
            "--per-seed-time",
            "1",
            "--total-time",
            "1",
            "--perm-root",
            str(perm_root),
            "--target",
            str(target_path),
        ],
    )

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "source-shape probe fallback" in out
    assert "case-c2-loop-cursor" in out
    assert (perm_dir / "tier3_seed_0" / "base.c").read_text() == patched_source


def test_tier3_search_uses_frame_directed_seeds_and_scores_seed_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(HSD_CObj* cobj, int arg2) {\n"
        "    f32 far_val;\n"
        "    f32 bottom;\n"
        "    far_val = 2.0f;\n"
        "    bottom = (f32) arg2;\n"
        "    setup();\n"
        "    HSD_CObjSetFar(cobj, far_val);\n"
        "    HSD_CObjSetOrtho(cobj, 0.0f, bottom, 0.0f, 1.0f);\n"
        "}\n"
    )
    pcdump_path = tmp_path / "pcdump.txt"
    pcdump_path.write_text("baseline pcdump")
    target_path = tmp_path / "target.json"
    target_path.write_text(json.dumps({
        "function": "fn_80000000",
        "virtuals": {},
        "frame": {
            "frame_size": 144,
            "unused_ranges": [],
        },
    }))

    perm_root = tmp_path / "permuter"
    perm_dir = perm_root / "nonmatchings" / "fn_80000000"
    perm_dir.mkdir(parents=True)
    for name in ("target.o", "settings.toml"):
        (perm_dir / name).write_text("")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\n")

    wibo = tmp_path / "wibo"
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    wibo.write_text("")
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("")

    pre = object()
    parsed_fn = SimpleNamespace(name="fn_80000000", last_precolor_pass=lambda: pre)
    score_calls: list[str] = []
    captured_runs: list[dict] = []

    import src.mwcc_debug.symbol_bridge as symbol_bridge

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: "melee/mn/sample")
    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda path, function, root=None: pcdump_path)
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [parsed_fn])
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debug_cli, "find_function", lambda events, function: None)
    monkeypatch.setattr(debug_cli, "analyze_frame_from_function", lambda fn: {"frame_size": 152})
    monkeypatch.setattr(symbol_bridge, "list_bindings", lambda source, function, pass_obj: [])
    monkeypatch.setattr(tier3_mod, "plan_seeds", lambda bindings, budget, include_low_confidence: [])
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))

    def fake_score_function(fn, target_spec, events=None):
        score_calls.append("score")
        total = 34 if len(score_calls) == 1 else 8
        return SimpleNamespace(total=total)

    def fake_smoke_compile(*args, **kwargs):
        return tier3_mod.CompileResult(
            ok=True,
            stderr="",
            stdout="",
            one_line_reason="",
            pcdump_text="seed pcdump",
        )

    def fake_run_per_seed_permute(**kwargs):
        captured_runs.append(kwargs)
        return tier3_mod.PerSeedPermuteResult(
            seed_idx=kwargs["seed_idx"],
            plan=kwargs["plan"],
            seed_dir=kwargs["seed_dir"],
            best_candidate=kwargs["seed_dir"] / "base.c",
            best_score=kwargs["seed_score"],
            baseline_score=kwargs["baseline_score"],
            delta=kwargs["baseline_score"] - kwargs["seed_score"],
            ran_seconds=0.0,
            seed_score=kwargs["seed_score"],
        )

    monkeypatch.setattr(debug_cli, "score_function", fake_score_function)
    monkeypatch.setattr(tier3_mod, "smoke_compile", fake_smoke_compile)
    monkeypatch.setattr(tier3_mod, "run_per_seed_permute", fake_run_per_seed_permute)
    monkeypatch.setattr(tier3_mod, "rank_seed_results", lambda results: results)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "search",
            "-f",
            "fn_80000000",
            "--budget",
            "1",
            "--per-seed-time",
            "1",
            "--total-time",
            "1",
            "--perm-root",
            str(perm_root),
            "--target",
            str(target_path),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "frame-directed seed plans" in out
    assert "frame-direct-literal-at-final-fp-call" in out
    assert captured_runs
    assert captured_runs[0]["baseline_score"] == 34
    assert captured_runs[0]["seed_score"] == 8
    assert "HSD_CObjSetFar(cobj, 2.0f);" in (
        perm_dir / "tier3_seed_0" / "base.c"
    ).read_text()


def test_debug_guide_warns_when_no_target_is_loaded(monkeypatch, tmp_path: Path) -> None:
    pcdump = tmp_path / "sample.pcdump.txt"
    pcdump.write_text("placeholder\n")
    fn = SimpleNamespace(name="fn_80000000")
    score = SimpleNamespace(targeted=0, matched=0, virtual_distance=0, spill_unexpected=[], spill_missing=[])

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda path, function: pcdump)
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [fn])
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debug_cli, "find_function", lambda events, function: [])
    monkeypatch.setattr(debug_cli, "score_function", lambda parsed_fn, spec, events=None: score)
    monkeypatch.setattr(debug_cli, "suggest", lambda parsed_fn, result, events=None: [])

    result = runner.invoke(app, ["debug", "inspect", "guide", "-f", "fn_80000000"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "No target spec was provided" in out
    assert "Do not derive a target from this same current pcdump" in out
    assert "reference/forced target spec" in out
    assert "debug inspect diagnose fn_80000000" in out
    assert "debug inspect ceiling fn_80000000" not in out
    assert "debug target derive -f fn_80000000 >" not in out
    assert "current coloring matches target" not in out


def test_debug_guide_warns_when_target_matches_current_pcdump(monkeypatch, tmp_path: Path) -> None:
    pcdump = tmp_path / "sample.pcdump.txt"
    pcdump.write_text("placeholder\n")
    target = tmp_path / "target.yaml"
    target.write_text("virtuals: {}\n")
    fn = SimpleNamespace(name="fn_80000000")
    score = SimpleNamespace(targeted=1, matched=1, virtual_distance=0, spill_unexpected=[], spill_missing=[])

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda path, function: pcdump)
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [fn])
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(debug_cli, "find_function", lambda events, function: [])
    monkeypatch.setattr(debug_cli, "_load_target_spec", lambda path: {"virtuals": {32: 31}})
    monkeypatch.setattr(debug_cli, "score_function", lambda parsed_fn, spec, events=None: score)
    monkeypatch.setattr(debug_cli, "suggest", lambda parsed_fn, result, events=None: [])

    result = runner.invoke(
        app,
        ["debug", "inspect", "guide", "-f", "fn_80000000", "--target", str(target)],
    )

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "Target spec currently matches this pcdump" in out
    assert "reference/forced target spec" in out


def test_virtual_to_var_compiler_temp_exits_success(monkeypatch, tmp_path: Path) -> None:
    import src.mwcc_debug.symbol_bridge as symbol_bridge

    pcdump = tmp_path / "sample.pcdump.txt"
    pcdump.write_text("placeholder\n")
    source = tmp_path / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n")
    pre = object()
    fn = SimpleNamespace(name="fn_80000000", last_precolor_pass=lambda: pre)
    first_def = SimpleNamespace(
        block_idx=0,
        opcode="lwz",
        operands="r70, 0(r3)",
        annotations=[],
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", lambda path, function, melee_root=None: pcdump)
    monkeypatch.setattr(debug_cli, "parse_pcdump", lambda text: [fn])
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, melee_root: "melee/mn/sample")
    monkeypatch.setattr(symbol_bridge, "find_var_for_virtual", lambda source, function, virtual, pre: None)
    monkeypatch.setattr(symbol_bridge, "find_first_def", lambda virtual, pre: first_def)

    result = runner.invoke(
        app,
        ["debug", "inspect", "virtual-to-var", "-f", "fn_80000000", "r70", str(pcdump)],
    )

    assert result.exit_code == 0
    err = strip_ansi(result.stderr)
    assert "likely a compiler-introduced temp" in err
    assert "first defining op" in err


def test_virtual_to_var_surfaces_call_return_copy_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text(textwrap.dedent("""\
        void fn_80000002(void* entity) {
            int result;
            int b34;
            result = helper_fn(entity);
            b34 = result;
            if (b34 == 0) {
                sink();
            }
        }
    """))
    pcdump = tmp_path / "sample.pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
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
    """))

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/mn/sample",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "virtual-to-var",
            "-f",
            "fn_80000002",
            "r40",
            str(pcdump),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "helper_fn(entity) -> result (call-return/copy-chain)" in out
    assert "chain:  r40 <- r43 <- r59 <- r3" in out
    assert "call:   BEFORE GLOBAL OPTIMIZATION B19:0 bl helper_fn" in out
    assert "use:    BEFORE GLOBAL OPTIMIZATION B33:0 cmpi cr0,r40,0" in out
    assert "no source variable bound" not in result.stderr


def test_virtual_to_var_accepts_fpr_class_and_reports_fpr_first_def(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000004(void) {}\n")
    pcdump = tmp_path / "sample.pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000004
        BEFORE REGISTER COLORING
        fn_80000004
        B0: Succ={} Pred={} Labels={}
            bl helper
            frsp f42,f1
            stfs f42,0x30(r1)
        COLORGRAPH DECISIONS (class=1, result=1, n_nodes=1)
          iter ig_idx phys degree nIntfr flags
            0 42 r6 0 0 0x00
    """))

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/mn/sample",
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "virtual-to-var",
            "-f",
            "fn_80000004",
            "f42",
            str(pcdump),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["virtual"] == 42
    assert payload["register_class"] == "fpr"
    assert payload["class_id"] == 1
    assert payload["assigned_reg"] == "f6"
    assert payload["found"] is False
    assert payload["source"]["kind"] == "fpr-temp"
    assert payload["source"]["expression"] == "frsp f42,f1"
    assert payload["first_def"]["opcode"] == "frsp"

    class_result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "virtual-to-var",
            "-f",
            "fn_80000004",
            "42",
            str(pcdump),
            "--class",
            "fpr",
            "--json",
        ],
    )
    assert class_result.exit_code == 0, class_result.stdout + class_result.stderr
    class_payload = json.loads(class_result.stdout)
    assert class_payload["register_class"] == "fpr"
    assert class_payload["source"]["expression"] == "frsp f42,f1"


def test_auto_verify_expensive_restore_refusal_does_not_fail_command() -> None:
    result = {
        "ran": True,
        "status": "restore_failed",
        "cleanup_complete": False,
        "restore": {
            "returncode": 125,
            "stderr_tail": "[restore] refusing to launch restore: ninja dry-run would run 91 ninja step(s)",
        },
    }

    assert debug_cli._auto_verify_failure_exit_code(result) is None


def test_auto_verify_zero_delta_is_not_actionable() -> None:
    result = {
        "ran": True,
        "status": "ok",
        "baseline_pct": 85.14802,
        "new_pct": 85.14802,
        "delta": 0.0,
    }

    debug_cli._annotate_auto_verify_actionability(result)

    assert result["actionability"] == "no_improvement"
    assert result["actionable"] is False
    assert "did not move" in result["actionability_note"]
