"""Tests for match-iter-first verification helpers."""

from __future__ import annotations

import pathlib
import subprocess
import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app
from src.cli import debug as debug_cli
from src.mwcc_debug.cache import cache_path
from src.mwcc_debug.colorgraph_parser import (
    ColorgraphDecision,
    ColorgraphSection,
    FunctionEvents,
)
from src.mwcc_debug.parser import Block, Instruction, Pass


CLI_CWD = pathlib.Path(__file__).parent.parent
MELEE_ROOT = CLI_CWD.parent.parent
runner = CliRunner()


def _patch_match_iter_first_cli_inputs(
    monkeypatch,
    tmp_path: pathlib.Path,
    *,
    expected_def: bool = True,
) -> tuple[pathlib.Path, pathlib.Path]:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    pcdump_path = tmp_path / "pcdump.txt"
    pcdump_path.write_text("Starting function fn_test\n", encoding="utf-8")
    asm_path = tmp_path / "expected.s"
    asm_path.write_text("fn_test:\n", encoding="utf-8")
    instruction = Instruction(
        opcode="mr",
        operands="r31,r3",
        annotations=[],
        regs=[("r", 31), ("r", 3)],
    )
    events = FunctionEvents(
        name="fn_test",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=1,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=33,
                        assigned_reg=27,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )

    class FakePcdumpFunction:
        name = "fn_test"

        def last_precolor_pass(self):
            return Pass(name="BEFORE REGISTER COLORING", blocks=[])

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump, function, melee_root, require_fresh=True: pcdump_path,
    )
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        debug_cli,
        "asm_extract_function",
        lambda text, function: SimpleNamespace(instructions=[instruction]),
    )
    monkeypatch.setattr(debug_cli, "asm_parse_prologue_end", lambda _instrs: 0)
    monkeypatch.setattr(
        debug_cli,
        "asm_find_first_def",
        lambda body, target_reg, reg_kind: (
            (0, instruction) if expected_def else None
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "match_virtual_for_expected_def",
        lambda **_kwargs: SimpleNamespace(
            ig_idx=33,
            virtual=33,
            instruction_index=0,
            confidence="exact",
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "parse_pcdump",
        lambda _text: [FakePcdumpFunction()],
    )
    monkeypatch.setattr(debug_cli, "parse_hook_events", lambda _text: [])
    monkeypatch.setattr(debug_cli, "find_function", lambda _events, function: events)
    return pcdump_path, asm_path


def test_pcdump_local_help_exposes_force_iter_first_function_scope() -> None:
    proc = subprocess.run(
        ["python", "-m", "src.cli", "debug", "dump", "local", "--help"],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--force-iter-first-fn" in proc.stdout
    assert "--force-iter-first-class" in proc.stdout
    assert "--force-iter-first-iter" in proc.stdout
    assert "--force-select-order" in proc.stdout
    assert "--force-select-order-class" in proc.stdout
    assert "Scope --force-iter-first" in proc.stdout
    assert "selection order" in proc.stdout


def test_match_iter_first_help_documents_auto_verify_cleanup_contract() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "target", "match-iter-first",
            "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "MWCC_DEBUG_RESTORE_TIMEOUT" in proc.stdout
    assert "MWCC_DEBUG_HANG_TIMEOUT" in proc.stdout
    assert "cleanup_complete=false" in proc.stdout
    assert "non-zero" in proc.stdout
    assert "--force-vector" in proc.stdout
    assert "integrated checkdiff" in proc.stdout
    assert "gpr-volatile" in proc.stdout


def test_force_phys_from_diff_help_documents_inputs_and_verification() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "target",
            "force-phys-from-diff", "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--checkdiff-json" in proc.stdout
    assert "--allow-stale-pcd" in proc.stdout
    assert "--verify" in proc.stdout
    assert "register-only checkdiff" in proc.stdout
    assert "force-vector" in proc.stdout


def test_match_iter_first_rejects_stale_auto_cache_by_default(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    cached = cache_path(melee_root, "melee/mn/sample")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("Starting function fn_80000000\n", encoding="utf-8")
    cached.with_suffix(".hash").write_text("0" * 64 + "\n", encoding="ascii")

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
            "target",
            "match-iter-first",
            "-f",
            "fn_80000000",
        ],
    )

    assert result.exit_code == 4
    assert "cached pcdump is stale" in result.stdout + result.stderr
    assert "--allow-stale-pcdump" in result.stdout + result.stderr


def test_match_iter_first_force_vector_auto_uses_derived_vector(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    pcdump_path, asm_path = _patch_match_iter_first_cli_inputs(
        monkeypatch,
        tmp_path,
    )
    captured: dict[str, list[debug_cli._ForceVectorEntry]] = {}

    def fake_run_force_vector_auto_verify(**kwargs):
        captured["entries"] = kwargs["entries"]
        return {"union": {"status": "match", "match": True}, "probes": []}

    monkeypatch.setattr(
        debug_cli,
        "_run_force_vector_auto_verify",
        fake_run_force_vector_auto_verify,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "match-iter-first",
            "-f",
            "fn_test",
            str(pcdump_path),
            "--asm",
            str(asm_path),
            "--regs",
            "r31",
            "--force-vector",
            "auto",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    entries = captured["entries"]
    assert [
        (entry.kind, entry.class_id, entry.ig_idx, entry.phys)
        for entry in entries
    ] == [
        ("force_phys", 0, 33, 31),
    ]
    assert '"force_vector": "class0:ig33:phys=r31"' in result.stdout
    assert '"ran": true' in result.stdout


def test_match_iter_first_force_vector_auto_reports_empty_derived_vector(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    pcdump_path, asm_path = _patch_match_iter_first_cli_inputs(
        monkeypatch,
        tmp_path,
        expected_def=False,
    )

    def fail_run_force_vector_auto_verify(**_kwargs):
        raise AssertionError("empty auto vector must not run verification")

    monkeypatch.setattr(
        debug_cli,
        "_run_force_vector_auto_verify",
        fail_run_force_vector_auto_verify,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "match-iter-first",
            "-f",
            "fn_test",
            str(pcdump_path),
            "--asm",
            str(asm_path),
            "--regs",
            "r31",
            "--force-vector",
            "auto",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert '"force_vector": ""' in result.stdout
    assert '"force_vector_verify": {' in result.stdout
    assert '"ran": false' in result.stdout
    assert "no force-vector targets were derived" in result.stdout


def test_match_iter_first_reg_parser_accepts_fpr_tokens() -> None:
    regs = debug_cli._parse_match_iter_first_regs("f31,f30,r29")

    assert [reg.name for reg in regs] == ["f31", "f30", "r29"]
    assert [(reg.kind, reg.number) for reg in regs] == [
        ("f", 31),
        ("f", 30),
        ("r", 29),
    ]


def test_match_iter_first_reg_parser_expands_callee_alias_and_ranges() -> None:
    regs = debug_cli._parse_match_iter_first_regs("gpr-callee,f31-f30")

    assert [reg.name for reg in regs] == [
        "r31", "r30", "r29", "r28", "r27", "r26", "r25", "f31", "f30",
    ]


def test_match_iter_first_reg_parser_expands_volatile_aliases() -> None:
    regs = debug_cli._parse_match_iter_first_regs("gpr-volatile,r0")

    assert [reg.name for reg in regs] == [
        "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12",
        "r0",
    ]


def test_match_iter_first_vector_keeps_full_target_order_and_current_regs() -> None:
    events = FunctionEvents(
        name="fn_test",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=3,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=33,
                        assigned_reg=27,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=1,
                        ig_idx=40,
                        assigned_reg=26,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=2,
                        ig_idx=45,
                        assigned_reg=29,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )
    results = [
        {"status": "ok", "kind": "r", "reg": 31, "reg_name": "r31", "ig_idx": 33},
        {"status": "ok", "kind": "r", "reg": 30, "reg_name": "r30", "ig_idx": 40},
        {"status": "ok", "kind": "r", "reg": 29, "reg_name": "r29", "ig_idx": 45},
    ]

    vector = debug_cli._build_match_iter_first_target_vector(results, events)

    assert vector["force_iter_first"] == [33, 40, 45]
    assert vector["force_iter_first_csv"] == "33,40,45"
    assert vector["force_phys"] == {"33": 31, "40": 30, "45": 29}
    assert vector["force_phys_unscoped_csv"] == "33:31,40:30,45:29"
    assert vector["force_phys_csv"] == "0:33:31,0:40:30,0:45:29"
    assert vector["force_vector"] == (
        "class0:ig33:phys=r31,"
        "class0:ig40:phys=r30,"
        "class0:ig45:phys=r29"
    )
    assert [target["class_id"] for target in vector["targets"]] == [0, 0, 0]
    assert [target["force_vector_entry"] for target in vector["targets"]] == [
        "class0:ig33:phys=r31",
        "class0:ig40:phys=r30",
        "class0:ig45:phys=r29",
    ]
    assert [target["current_reg_name"] for target in vector["targets"]] == [
        "r27", "r26", "r29",
    ]
    assert [target["already_target"] for target in vector["targets"]] == [
        False, False, True,
    ]
    assert vector["force_vector_runnable"] is True
    assert vector["conflicts"] == []


def test_match_iter_first_vector_marks_all_already_target_as_dead_end() -> None:
    events = FunctionEvents(
        name="fn_test",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=3,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=33,
                        assigned_reg=4,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=1,
                        ig_idx=40,
                        assigned_reg=5,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )
    results = [
        {"status": "ok", "kind": "r", "reg": 4, "reg_name": "r4", "ig_idx": 33},
        {"status": "ok", "kind": "r", "reg": 5, "reg_name": "r5", "ig_idx": 40},
    ]

    vector = debug_cli._build_match_iter_first_target_vector(results, events)

    actionability = vector["actionability"]
    assert actionability["status"] == "already-satisfied"
    assert actionability["work_bucket"] == "source-lifetime/callee-save-shape"
    assert actionability["already_target_count"] == 2
    assert actionability["needs_move_count"] == 0
    assert "target vector already satisfied" in actionability["summary"]
    assert "source lifetime" in actionability["next_step"]
    assert "force-vector" in actionability["avoid"]


def test_auto_verify_no_improvement_demotes_target_vector_guidance() -> None:
    vector = {
        "force_vector": "class0:ig33:phys=r4",
        "force_vector_recommended": True,
        "actionability": {
            "status": "needs-move",
            "work_bucket": "allocator-target-vector",
            "summary": "target vector has runnable entries that need movement",
            "next_step": "Use the force-vector probe as a diagnostic test.",
            "target_count": 1,
            "runnable_target_count": 1,
            "already_target_count": 0,
            "needs_move_count": 1,
            "unknown_current_count": 0,
        },
    }
    auto_verify = {
        "ran": True,
        "baseline_pct": 98.0,
        "new_pct": 98.0,
        "delta": 0.0,
    }

    debug_cli._annotate_auto_verify_actionability(auto_verify)
    effective = debug_cli._target_vector_after_auto_verify(vector, auto_verify)

    assert effective["force_vector_recommended"] is False
    assert effective["actionability"]["status"] == "auto-verify-no-improvement"
    assert effective["actionability"]["work_bucket"] == (
        "source-lifetime/callee-save-shape"
    )
    assert "no improvement" in effective["actionability"]["summary"]
    assert "source-shape" in effective["actionability"]["next_step"]
    assert "force-vector" in effective["actionability"]["avoid"]
    assert vector["force_vector_recommended"] is True


def test_match_iter_first_vector_suppresses_conflicting_duplicate_ig_force_phys() -> None:
    events = FunctionEvents(
        name="fn_test",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=1,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=41,
                        assigned_reg=4,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )
    results = [
        {
            "status": "ok",
            "kind": "r",
            "reg": 5,
            "reg_name": "r5",
            "ig_idx": 41,
            "confidence": "ambiguous",
        },
        {
            "status": "ok",
            "kind": "r",
            "reg": 6,
            "reg_name": "r6",
            "ig_idx": 41,
            "confidence": "ambiguous",
        },
    ]

    vector = debug_cli._build_match_iter_first_target_vector(results, events)

    assert vector["force_iter_first"] == [41]
    assert vector["force_phys"] == {}
    assert vector["force_phys_csv"] == ""
    assert vector["force_vector"] == ""
    assert vector["force_vector_runnable"] is False
    assert vector["conflicts"] == [
        {
            "class_id": 0,
            "ig_idx": 41,
            "target_regs": [5, 6],
            "target_reg_names": ["r5", "r6"],
        }
    ]
    assert [target["force_vector_runnable"] for target in vector["targets"]] == [
        False,
        False,
    ]


def test_force_phys_from_diff_derives_repeated_and_dotted_targets() -> None:
    target_asm = [
        "<fn_test>:",
        "+000: 7c 08 02 a6 \tmflr    r0",
        "+004: 94 21 ff e0 \tstwu    r1,-32(r1)",
        "+008: 88 9f 22 27 \tlbz     r4,8743(r31)",
        "+00c: 54 84 ff ff \trlwinm. r4,r4,31,31,31",
        "+010: 3b c0 00 00 \tli      r30,0",
        "+014: 3b de 00 01 \taddi    r30,r30,1",
    ]
    current_asm = [
        "<fn_test>:",
        "+000: 7c 08 02 a6 \tmflr    r0",
        "+004: 94 21 ff e0 \tstwu    r1,-32(r1)",
        "+008: 88 1f 22 27 \tlbz     r0,8743(r31)",
        "+00c: 54 03 ff ff \trlwinm. r3,r0,31,31,31",
        "+010: 3b a0 00 00 \tli      r29,0",
        "+014: 3b bd 00 01 \taddi    r29,r29,1",
    ]
    pre_pass = Pass(
        name="BEFORE REGISTER COLORING",
        blocks=[
            Block(
                index=0,
                succ=[],
                pred=[],
                labels=[],
                instructions=[
                    Instruction(
                        opcode="lbz",
                        operands="r58,8743(r32)",
                        annotations=[],
                        regs=[("r", 58), ("r", 32)],
                    ),
                    Instruction(
                        opcode="rlwinm",
                        operands="r45,r58,31,31,31",
                        annotations=[],
                        regs=[("r", 45), ("r", 58)],
                    ),
                    Instruction(
                        opcode="li",
                        operands="r34,0",
                        annotations=[],
                        regs=[("r", 34)],
                    ),
                    Instruction(
                        opcode="addi",
                        operands="r34,r34,1",
                        annotations=[],
                        regs=[("r", 34), ("r", 34)],
                    ),
                    Instruction(
                        opcode="li",
                        operands="r36,0",
                        annotations=[],
                        regs=[("r", 36)],
                    ),
                    Instruction(
                        opcode="addi",
                        operands="r36,r36,1",
                        annotations=[],
                        regs=[("r", 36), ("r", 36)],
                    ),
                ],
            ),
        ],
    )
    events = FunctionEvents(
        name="fn_test",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=4,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=58,
                        assigned_reg=0,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=1,
                        ig_idx=45,
                        assigned_reg=3,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=2,
                        ig_idx=34,
                        assigned_reg=30,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=3,
                        ig_idx=36,
                        assigned_reg=29,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )

    vector = debug_cli._derive_force_phys_from_register_diff_lines(
        target_asm,
        current_asm,
        pre_pass,
        events,
    )

    assert vector["force_phys_csv"] == "0:58:4,0:45:4,0:36:30"
    assert vector["force_vector"] == (
        "class0:ig58:phys=r4,"
        "class0:ig45:phys=r4,"
        "class0:ig36:phys=r30"
    )
    assert [target["occurrence_count"] for target in vector["targets"]] == [
        1, 1, 2,
    ]
    assert [target["current_reg_name"] for target in vector["targets"]] == [
        "r0", "r3", "r29",
    ]
    assert [target["already_target"] for target in vector["targets"]] == [
        False, False, False,
    ]
    assert [target["confidence"] for target in vector["targets"]] == [
        "exact", "exact", "current-reg",
    ]


def test_force_phys_from_diff_aligns_stack_slots_with_frame_delta() -> None:
    target_asm = [
        "<fn_frame>:",
        "+000: 7c 08 02 a6 \tmflr    r0",
        "+004: 94 21 ff d0 \tstwu    r1,-48(r1)",
        "+008: 83 e1 00 28 \tlwz     r31,40(r1)",
        "+00c: 83 c1 00 2c \tlwz     r30,44(r1)",
    ]
    current_asm = [
        "<fn_frame>:",
        "+000: 7c 08 02 a6 \tmflr    r0",
        "+004: 94 21 ff c8 \tstwu    r1,-56(r1)",
        "+008: 83 a1 00 28 \tlwz     r29,40(r1)",
        "+00c: 83 c1 00 30 \tlwz     r30,48(r1)",
        "+010: 83 e1 00 34 \tlwz     r31,52(r1)",
    ]
    pre_pass = Pass(
        name="BEFORE REGISTER COLORING",
        blocks=[
            Block(
                index=0,
                succ=[],
                pred=[],
                labels=[],
                instructions=[
                    Instruction(
                        opcode="lwz",
                        operands="r35,40(r1)",
                        annotations=[],
                        regs=[("r", 35), ("r", 1)],
                    ),
                    Instruction(
                        opcode="lwz",
                        operands="r36,44(r1)",
                        annotations=[],
                        regs=[("r", 36), ("r", 1)],
                    ),
                ],
            ),
        ],
    )
    events = FunctionEvents(
        name="fn_frame",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=2,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=35,
                        assigned_reg=30,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                    ColorgraphDecision(
                        iter_idx=1,
                        ig_idx=36,
                        assigned_reg=31,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )

    vector = debug_cli._derive_force_phys_from_register_diff_lines(
        target_asm,
        current_asm,
        pre_pass,
        events,
    )

    assert vector["frame_alignment"]["frame_delta"] == -8
    assert vector["force_phys_csv"] == "0:35:31,0:36:30"
    assert vector["conflicts"] == []
    assert [
        occurrence["line_index"]
        for target in vector["targets"]
        for occurrence in target["occurrences"]
    ] == [3, 4]


def test_force_phys_from_diff_excludes_conflicted_igs_from_runnable_vector() -> None:
    target_asm = [
        "<fn_conflict>:",
        "+000: 7c 08 02 a6 \tmflr    r0",
        "+004: 94 21 ff e0 \tstwu    r1,-32(r1)",
        "+008: 3b e0 00 00 \tli      r31,0",
        "+00c: 3b c0 00 00 \tli      r30,0",
    ]
    current_asm = [
        "<fn_conflict>:",
        "+000: 7c 08 02 a6 \tmflr    r0",
        "+004: 94 21 ff e0 \tstwu    r1,-32(r1)",
        "+008: 3b a0 00 00 \tli      r29,0",
        "+00c: 3b a0 00 00 \tli      r29,0",
    ]
    pre_pass = Pass(
        name="BEFORE REGISTER COLORING",
        blocks=[
            Block(
                index=0,
                succ=[],
                pred=[],
                labels=[],
                instructions=[
                    Instruction(
                        opcode="li",
                        operands="r35,0",
                        annotations=[],
                        regs=[("r", 35)],
                    ),
                ],
            ),
        ],
    )
    events = FunctionEvents(
        name="fn_conflict",
        colorgraph_sections=[
            ColorgraphSection(
                class_id=0,
                result=1,
                n_nodes=1,
                decisions=[
                    ColorgraphDecision(
                        iter_idx=0,
                        ig_idx=35,
                        assigned_reg=29,
                        degree=0,
                        n_interferers=0,
                        flags=0,
                    ),
                ],
            ),
        ],
    )

    vector = debug_cli._derive_force_phys_from_register_diff_lines(
        target_asm,
        current_asm,
        pre_pass,
        events,
    )

    assert vector["force_phys"] == {}
    assert vector["force_phys_csv"] == ""
    assert vector["force_vector"] == ""
    assert vector["conflicts"] == [
        {
            "class_id": 0,
            "kind": "r",
            "ig_idx": 35,
            "existing_phys": 31,
            "conflicting_phys": 30,
            "line_index": 4,
            "target_asm": "+00c: 3b c0 00 00 \tli      r30,0",
            "current_asm": "+00c: 3b a0 00 00 \tli      r29,0",
        }
    ]


def test_restore_object_report_help_exposes_guarded_cleanup_command() -> None:
    proc = subprocess.run(
        [
            "python", "-m", "src.cli", "debug", "dump", "restore-object-report",
            "--help",
        ],
        cwd=CLI_CWD,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0
    assert "--max-steps" in proc.stdout
    assert "--force" in proc.stdout
    assert "MWCC_DEBUG_RESTORE_MAX_STEPS" in proc.stdout


def test_match_iter_first_auto_verify_command_scopes_force_iter_first() -> None:
    src_path = MELEE_ROOT / "src" / "melee" / "mn" / "mnvibration.c"

    cmd = debug_cli._build_match_iter_first_auto_verify_cmd(
        src_path=src_path,
        ig_csv="151,48,45,153",
        function="fn_80247510",
    )

    assert "--force-iter-first" in cmd
    assert "151,48,45,153" in cmd
    assert "--force-iter-first-fn" in cmd
    assert "fn_80247510" in cmd
    assert "/dev/null" not in cmd
    output_path = pathlib.Path(cmd[cmd.index("-o") + 1])
    assert output_path.parent == src_path.parent
    assert output_path.name.startswith(".fn_80247510.auto-verify.")


def test_force_vector_parser_accepts_phys_coalesce_iter_and_iter_first() -> None:
    entries = debug_cli._parse_force_vector(
        "ig40:phys=r30,ig42:coalesce=38,class0:iter5:phys=r31,ig50:iter-first"
    )

    assert [entry.kind for entry in entries] == [
        "force_phys",
        "force_coalesce",
        "force_phys_iter",
        "force_iter_first",
    ]
    assert entries[0].ig_idx == 40
    assert entries[0].phys == 30
    assert entries[1].ig_idx == 42
    assert entries[1].root == 38
    assert entries[2].class_id == 0
    assert entries[2].iter_idx == 5
    assert entries[2].phys == 31
    assert entries[3].ig_idx == 50


def test_force_vector_parser_accepts_class_scoped_iter_first() -> None:
    entries = debug_cli._parse_force_vector(
        "class1:ig50:iter-first,class1:iter4:iter-first"
    )

    assert [entry.kind for entry in entries] == [
        "force_iter_first",
        "force_iter_first_iter",
    ]
    assert entries[0].class_id == 1
    assert entries[0].ig_idx == 50
    assert entries[1].class_id == 1
    assert entries[1].iter_idx == 4


def test_force_phys_normalizer_preserves_class_scope_for_dll() -> None:
    dll_value, warnings = debug_cli._normalize_force_phys(
        "gpr:40:29,1:50:31"
    )

    assert dll_value == "0:40:29,1:50:31"
    assert not any("does not support class filtering" in w for w in warnings)


def test_force_vector_parser_accepts_class_scoped_select_order() -> None:
    entries = debug_cli._parse_force_vector(
        "class0:ig40:select-first,class0:ig32:select-first"
    )

    assert [entry.kind for entry in entries] == [
        "force_select_order",
        "force_select_order",
    ]
    assert [entry.class_id for entry in entries] == [0, 0]
    assert [entry.ig_idx for entry in entries] == [40, 32]


def test_force_vector_parser_accepts_class_scoped_force_phys_by_ig() -> None:
    entries = debug_cli._parse_force_vector("class0:ig40:phys=r29")

    assert [entry.kind for entry in entries] == ["force_phys"]
    assert entries[0].class_id == 0
    assert entries[0].ig_idx == 40
    assert entries[0].phys == 29


def test_force_vector_auto_verify_command_scopes_all_force_types(
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector(
        "ig40:phys=r30,ig42:coalesce=38,class0:iter5:phys=r31,ig50:iter-first"
    )
    output = tmp_path / "forced.pcdump.txt"

    cmd = debug_cli._build_force_vector_auto_verify_cmd(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        output_path=output,
        checkdiff_timeout=12.5,
    )

    assert cmd[:6] == [
        sys.executable,
        "-m",
        "src.cli",
        "debug",
        "dump",
        "local",
    ]
    assert "--force-phys" in cmd
    assert cmd[cmd.index("--force-phys") + 1] == "40:30"
    assert "--force-phys-iter" in cmd
    assert cmd[cmd.index("--force-phys-iter") + 1] == "0:5:31"
    assert "--force-phys-fn" in cmd
    assert cmd[cmd.index("--force-phys-fn") + 1] == "fn_test"
    assert "--force-coalesce" in cmd
    assert cmd[cmd.index("--force-coalesce") + 1] == "42=38"
    assert "--force-coalesce-fn" in cmd
    assert cmd[cmd.index("--force-coalesce-fn") + 1] == "fn_test"
    assert "--force-iter-first" in cmd
    assert cmd[cmd.index("--force-iter-first") + 1] == "50"
    assert "--force-iter-first-fn" in cmd
    assert cmd[cmd.index("--force-iter-first-fn") + 1] == "fn_test"
    assert "--diff" in cmd
    assert "--function" in cmd
    assert cmd[cmd.index("--function") + 1] == "fn_test"
    assert "--checkdiff-timeout" in cmd
    assert cmd[cmd.index("--checkdiff-timeout") + 1] == "12.5"
    assert str(output) in cmd


def test_force_vector_auto_verify_command_scopes_select_order_by_class(
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector(
        "class0:ig40:select-first,class0:ig32:select-first"
    )

    cmd = debug_cli._build_force_vector_auto_verify_cmd(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        output_path=tmp_path / "forced.pcdump.txt",
    )

    assert "--force-select-order" in cmd
    assert cmd[cmd.index("--force-select-order") + 1] == "40,32"
    assert "--force-select-order-class" in cmd
    assert cmd[cmd.index("--force-select-order-class") + 1] == "0"
    assert "--force-select-order-fn" in cmd
    assert cmd[cmd.index("--force-select-order-fn") + 1] == "fn_test"


def test_force_vector_auto_verify_command_preserves_class_scoped_force_phys(
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector("class0:ig40:phys=r29")

    cmd = debug_cli._build_force_vector_auto_verify_cmd(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        output_path=tmp_path / "forced.pcdump.txt",
    )

    assert "--force-phys" in cmd
    assert cmd[cmd.index("--force-phys") + 1] == "0:40:29"
    assert "--force-phys-fn" in cmd
    assert cmd[cmd.index("--force-phys-fn") + 1] == "fn_test"


def test_force_vector_auto_verify_command_scopes_iter_first_by_class(
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector(
        "class1:ig50:iter-first,class1:iter4:iter-first"
    )

    cmd = debug_cli._build_force_vector_auto_verify_cmd(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        output_path=tmp_path / "forced.pcdump.txt",
    )

    assert "--force-iter-first" in cmd
    assert cmd[cmd.index("--force-iter-first") + 1] == "50"
    assert "--force-iter-first-class" in cmd
    assert cmd[cmd.index("--force-iter-first-class") + 1] == "1"
    assert "--force-iter-first-iter" in cmd
    assert cmd[cmd.index("--force-iter-first-iter") + 1] == "1:4"
    assert "--force-iter-first-fn" in cmd
    assert cmd[cmd.index("--force-iter-first-fn") + 1] == "fn_test"


def test_force_vector_auto_verify_runs_union_singles_and_prefixes(
    monkeypatch,
    tmp_path: pathlib.Path,
) -> None:
    src_path = tmp_path / "sample.c"
    src_path.write_text("void fn_test(void) {}\n", encoding="utf-8")
    entries = debug_cli._parse_force_vector(
        "ig40:phys=r30,ig42:coalesce=38,ig50:iter-first"
    )
    calls: list[list[str]] = []

    def fake_run(cmd, *, cwd, status_label, phase="testing",
                 status_interval_s=10.0, timeout_s=None, env=None):
        calls.append(cmd)
        stdout = "[diff] MATCH - function bytes are identical.\n" if "union" in status_label else "diff remained\n"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(
        debug_cli,
        "_run_auto_verify_command_with_status",
        fake_run,
    )

    result = debug_cli._run_force_vector_auto_verify(
        src_path=src_path,
        function="fn_test",
        entries=entries,
        melee_root=tmp_path,
        checkdiff_timeout=30.0,
        run_diagnostic_probes=True,
    )

    labels = [probe["label"] for probe in result["probes"]]
    assert result["union"]["match"] is True
    assert labels == [
        "single[1]",
        "single[2]",
        "single[3]",
        "prefix[1..2]",
    ]
    assert all(probe["match"] is False for probe in result["probes"])
    assert len(calls) == 5
    assert all("--diff" in call for call in calls)
    assert calls[0][calls[0].index("--force-phys") + 1] == "40:30"
    assert calls[0][calls[0].index("--force-coalesce") + 1] == "42=38"
    assert calls[0][calls[0].index("--force-iter-first") + 1] == "50"


def test_auto_verify_runner_emits_periodic_status(capsys) -> None:
    cmd = [
        sys.executable,
        "-c",
        "import time; time.sleep(0.2); print('done')",
    ]

    result = debug_cli._run_auto_verify_command_with_status(
        cmd,
        cwd=CLI_CWD,
        status_label="--force-iter-first 151 --force-iter-first-fn fn_test",
        status_interval_s=0.05,
    )

    captured = capsys.readouterr()
    assert result.returncode == 0
    assert "done" in result.stdout
    assert "testing --force-iter-first 151 --force-iter-first-fn fn_test" in (
        captured.err
    )
    assert "still running" in captured.err


def test_auto_verify_runner_times_out_restore_phase(capsys) -> None:
    cmd = [
        sys.executable,
        "-c",
        "import time; time.sleep(5)",
    ]

    result = debug_cli._run_auto_verify_command_with_status(
        cmd,
        cwd=CLI_CWD,
        status_label="clean object/report",
        phase="restoring object/report",
        status_interval_s=0.05,
        timeout_s=0.12,
    )

    captured = capsys.readouterr()
    assert result.returncode == 124
    assert "restoring object/report: clean object/report" in captured.err
    assert "still running" in captured.err
    assert "timed out" in result.stderr


def test_auto_verify_restore_timeout_inherits_hang_timeout(monkeypatch) -> None:
    monkeypatch.delenv("MWCC_DEBUG_RESTORE_TIMEOUT", raising=False)
    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "8")

    timeout_s, source = debug_cli._resolve_auto_verify_restore_timeout()

    assert timeout_s == 8.0
    assert source == "MWCC_DEBUG_HANG_TIMEOUT"


def test_auto_verify_restore_timeout_prefers_restore_env(monkeypatch) -> None:
    monkeypatch.setenv("MWCC_DEBUG_RESTORE_TIMEOUT", "12")
    monkeypatch.setenv("MWCC_DEBUG_HANG_TIMEOUT", "8")

    timeout_s, source = debug_cli._resolve_auto_verify_restore_timeout()

    assert timeout_s == 12.0
    assert source == "MWCC_DEBUG_RESTORE_TIMEOUT"


def test_auto_verify_restore_hint_explains_truncated_ninja_state() -> None:
    hint = debug_cli._auto_verify_restore_cleanup_hint(
        "ninja: warning: premature end of file; recovering\n"
    )

    assert "ninja -t recompact" in hint
    assert "restore-object-report" in hint
    assert ".ninja_deps" in hint
    assert "python configure.py" in hint


def test_hsd_assert_override_guidance_is_self_contained() -> None:
    guidance = debug_cli._format_hsd_assert_override_guidance()

    assert "MEMORY.md" not in guidance
    assert "#include <baselib/debug.h>" in guidance
    assert "#undef HSD_ASSERT" in guidance
    assert "__assert(<file_sym>, line, <fn_sym>)" in guidance
    assert "transitively" in guidance
    assert "may be neutral" in guidance
    assert "nearby affected functions" in guidance


def test_ninja_dry_run_step_count_uses_total_planned_steps() -> None:
    assert debug_cli._ninja_dry_run_planned_steps(
        "[1/969] Building C object\n"
        "[2/969] Building C object\n"
    ) == 969
    assert debug_cli._ninja_dry_run_planned_steps("ninja: no work to do.\n") == 0
    assert debug_cli._ninja_dry_run_planned_steps("touch foo.o\nlink report\n") == 2


def test_expensive_restore_guard_returns_failure_without_running_ninja() -> None:
    result = debug_cli._make_expensive_restore_result(
        ["ninja", "build/GALE01/src/melee/mn/mnvibration.o"],
        planned_steps=969,
        max_steps=64,
    )

    assert result.returncode == 125
    assert "would run 969 ninja step(s)" in result.stderr
    assert "MWCC_DEBUG_RESTORE_MAX_STEPS" in result.stderr
    assert "--force" in result.stderr


def test_expensive_restore_guard_explains_stale_metadata_and_preview() -> None:
    result = debug_cli._make_expensive_restore_result(
        ["ninja", "build/GALE01/src/melee/mn/mnvibration.o"],
        planned_steps=575,
        max_steps=64,
        dry_run_output=(
            "[1/575] Linking build/GALE01/report.json\n"
            "[2/575] Compiling src/melee/mn/mnvibration.c\n"
        ),
    )

    assert "dry-run preview" in result.stderr
    assert "[1/575] Linking build/GALE01/report.json" in result.stderr
    assert "report.json is older than build.ninja" in result.stderr
    assert "no metadata-only repair" in result.stderr


def test_auto_verify_restore_failure_requests_nonzero_exit() -> None:
    assert debug_cli._auto_verify_failure_exit_code({
        "ran": True,
        "restore": {"returncode": 124},
    }) == 124
    assert debug_cli._auto_verify_failure_exit_code({
        "ran": True,
        "restore": {"returncode": 0},
    }) is None
    assert debug_cli._auto_verify_failure_exit_code({"ran": False}) is None


def test_mwcc_debug_dll_has_iter_first_function_scope() -> None:
    dll_source = (MELEE_ROOT / "tools" / "mwcc_debug" / "mwcc_debug.c").read_text()

    assert "MWCC_DEBUG_FORCE_ITER_FIRST_FUNCTION" in dll_source
    assert "MWCC_DEBUG_FORCE_ITER_FIRST_CLASS" in dll_source
    assert "MWCC_DEBUG_FORCE_ITER_FIRST_ITER" in dll_source
    assert "g_iter_first_scope_fn_set" in dll_source
    assert "g_iter_first_scope_class_set" in dll_source
    assert "[FORCE_ITER_FIRST] scope skip" in dll_source


def test_mwcc_debug_dll_has_class_scoped_force_phys() -> None:
    dll_source = (MELEE_ROOT / "tools" / "mwcc_debug" / "mwcc_debug.c").read_text()

    assert "MWCC_DEBUG_FORCE_PHYS" in dll_source
    assert "rclass" in dll_source
    assert "g_overrides[k].rclass < 0" in dll_source
    assert "g_overrides[k].rclass == rclass" in dll_source
    assert "[FORCE_PHYS] class=%d" in dll_source


def test_mwcc_debug_dll_force_phys_parser_reports_overflow() -> None:
    dll_source = (MELEE_ROOT / "tools" / "mwcc_debug" / "mwcc_debug.c").read_text()

    assert "#define MAX_OVERRIDES 1024" in dll_source
    assert "#define MAX_ITER_OVERRIDES 1024" in dll_source
    assert "g_force_phys_parse_overflow" in dll_source
    assert "g_force_phys_iter_parse_overflow" in dll_source
    assert "[FORCE_PHYS] ERROR: override list exceeded parser capacity" in dll_source
    assert "[FORCE_PHYS_ITER] ERROR: override list exceeded parser capacity" in dll_source
    assert "MWCC_DEBUG_ENV_BUF_LEN" in dll_source
