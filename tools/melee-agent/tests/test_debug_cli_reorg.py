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
        ["debug", "target", "derive", "--help"],
        ["debug", "target", "match-iter-first", "--help"],
        ["debug", "target", "score-source", "--help"],
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
    fn_dir = perm_root / "nonmatchings" / "fn_80000000"
    assert (fn_dir / "settings.toml").exists()
    assert "func_name = \"fn_80000000\"" in (fn_dir / "settings.toml").read_text()


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
        lambda unit, function, root, fast_report=False: (91.25, None),
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
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["results"][0]["status"] == "ok"
    assert data["results"][0]["semantic_risk_bucket"] == "plausible-C-shape"
    assert data["results"][0]["match_pct"] == 95.6426
    assert calls.count(obj_cmd) == 2


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


def test_dump_local_force_phys_help_does_not_claim_class_filtering() -> None:
    result = runner.invoke(app, ["debug", "dump", "local", "--help"])

    assert result.exit_code == 0
    out = strip_ansi(result.stdout)
    assert "The DLL" in out
    assert "ignores the class prefix" in out
    assert "class-scoped, avoids ambiguous FP override" not in out


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
