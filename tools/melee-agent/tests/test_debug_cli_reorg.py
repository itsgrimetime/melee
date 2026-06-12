"""CLI surface tests for the workflow-oriented mwcc-debug command layout."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import textwrap
import tomllib
from contextlib import contextmanager
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
        ["debug", "suggest", "signatures", "--help"],
        ["debug", "suggest", "control-flow-shape", "--help"],
        ["debug", "suggest", "coalesce", "--help"],
        ["debug", "suggest", "schedule", "--help"],
        ["debug", "suggest", "inlines", "--help"],
        ["debug", "mutate", "decl-orders", "--help"],
        ["debug", "mutate", "control-flow-shape-search", "--help"],
        ["debug", "mutate", "frame-transform-search", "--help"],
        ["debug", "mutate", "indexed-struct-search", "--help"],
        ["debug", "mutate", "lifetime-layout", "--help"],
        ["debug", "permute", "run", "--help"],
        ["debug", "permute", "doctor", "--help"],
        ["debug", "permute", "verify", "--help"],
        ["debug", "permute", "remote", "--help"],
        ["debug", "permute", "remote", "doctor", "--help"],
        ["debug", "permute", "remote", "submit", "--help"],
        ["debug", "permute", "remote", "fetch", "--help"],
        ["debug", "permute", "remote", "triage", "--help"],
        ["debug", "util", "name-magic", "--help"],
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, (command, result.stdout)


def test_debug_cli_lazy_imports_reference_mwcc_debug_package() -> None:
    source = Path(debug_cli.__file__).resolve().read_text(encoding="utf-8")
    assert "from ..mwcc_debug" not in source


def test_indexed_struct_search_help_works() -> None:
    result = runner.invoke(
        debug_cli.debug_app,
        ["mutate", "indexed-struct-search", "--help"],
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.output
    assert "--score-match-percent" in result.output
    assert "--compile-probes" in result.output


def test_control_flow_shape_search_help_works() -> None:
    result = runner.invoke(
        debug_cli.debug_app,
        ["mutate", "control-flow-shape-search", "--help"],
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.output
    assert "--operator" in result.output
    assert "--score-match-percent" in result.output
    assert "--compile-probes" in result.output


def test_control_flow_shape_search_json_reports_no_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: None)

    result = runner.invoke(
        debug_cli.debug_app,
        ["mutate", "control-flow-shape-search", "-f", "fn_80000000", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "source-unavailable"
    assert payload["function"] == "fn_80000000"
    assert payload["source"] is None
    assert payload["generated_source_dir"] is None
    assert payload["probe_count"] == 0
    assert payload["probes"] == []
    assert payload["stop_condition"] == {
        "kind": "blocked",
        "blocker": "source-unavailable",
        "reason": "source file could not be resolved",
    }
    assert payload["variants"] == []


def test_control_flow_shape_search_json_scores_generated_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            int fn_80000000(int cond, int a, int b)
            {
                int x;
                x = cond ? a : b;
                return x;
            }
            """
        )
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return "pcdump text"

    def fake_score(
        path,
        *,
        function,
        melee_root,
        timeout=None,
        status=None,
        include_stack_slot=False,
    ):
        return debug_cli._SourceCandidateRealScore(100.0, None)

    monkeypatch.setattr(
        debug_cli,
        "_control_flow_compile_source_variant",
        fake_compile,
        raising=False,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fake_score,
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "control-flow-shape-search",
            "-f",
            "fn_80000000",
            "--json",
            "--operator",
            "ternary-to-if-else",
            "--max-probes",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] is None
    assert payload["function"] == "fn_80000000"
    assert payload["source"].endswith("src/melee/demo.c")
    assert Path(payload["generated_source_dir"]).exists()
    assert payload["stop_condition"]["kind"] == "validated"
    assert payload["stop_condition"]["blocker"] is None
    assert payload["probe_count"] == 1
    assert payload["probes"][0]["operator"] == "ternary-to-if-else"
    variant = payload["variants"][0]
    assert variant["status"] == "ok"
    assert variant["operator"] == "ternary-to-if-else"
    assert Path(variant["path"]).exists()
    assert variant["match_percent"] == 100.0
    assert variant["final_match_percent"] == 100.0
    assert variant["error"] is None
    assert Path(variant["source_retained"]).exists()
    assert variant["probe"]["provenance"]["kind"] == "control-flow-shape"


def _control_flow_shape_checkdiff_payload(function: str = "fn_80000000") -> dict:
    return {
        "function": function,
        "classification": {
            "primary": "control-flow-source-shape",
            "indexed_struct_pointer_materialization": {
                "expected_indexed_ops": ["lwz r7, 0x10(r6)"],
                "current_materialized_pointers": ["lwz r7, 0(r3)"],
            },
        },
        "target_asm": [
            "/* 0000 */ cmpwi r3, 0",
            "/* 0004 */ bne lbl_true",
            "/* 0008 */ li r0, 0",
            "/* 000C */ b lbl_done",
            "lbl_true:",
            "/* 0010 */ li r0, 1",
            "/* 0014 */ mulli r5, r4, 0x24",
            "/* 0018 */ add r6, r3, r5",
            "/* 001C */ lwz r7, 0x10(r6)",
        ],
        "current_asm": [
            "/* 0000 */ subfic r0, r3, 0",
            "/* 0004 */ cntlzw r0, r0",
            "/* 0008 */ srwi r0, r0, 5",
            "/* 000C */ bl fn_803AC168",
            "/* 0010 */ lwz r7, 0(r3)",
        ],
    }


def test_debug_suggest_signatures_json_from_saved_checkdiff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            void caller_fn(int rumble_setting)
            {
                helper((f32) rumble_setting);
            }
            """
        )
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(json.dumps({
        "function": "caller_fn",
        "classification": {"primary": "signature-type-mismatch"},
        "target_asm": [
            "/* 0000 */ mr r3, r31",
            "/* 0004 */ bl helper",
        ],
        "current_asm": [
            "/* 0000 */ fmr f1, f31",
            "/* 0004 */ bl helper",
        ],
        "fuzzy_match_percent": 97.5,
    }))
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["function"] == "caller_fn"
    assert report["checkdiff_source"] == str(payload_path)
    assert report["source"] == str(source)
    assert report["validation_enabled"] is False
    finding = report["findings"][0]
    assert finding["kind"] == "argument-bank-mismatch"
    assert finding["arg_index"] == 0
    action = finding["actions"][0]
    assert action["kind"] == "remove-call-arg-cast"
    assert action["patch"]["old"] == "(f32) rumble_setting"
    assert action["patch"]["new"] == "rumble_setting"
    assert action["rebucket"] is None
    assert report["summary"]["patch_candidate_count"] == 1
    assert report["summary"]["stop_condition"]["kind"] == (
        "unvalidated-patch-candidates"
    )


def test_debug_suggest_signatures_text_prints_summary_and_rebucket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        "void caller_fn(int value) { helper_b(value); }\n",
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-type-mismatch"},
            "target_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper_a",
            ],
            "current_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper_b",
            ],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "stop: rebucketed-audit-only" in result.output
    assert (
        "rebucket: call-offset-shift -> "
        "structural-reconstruction/call-target-shape"
    ) in result.output


def test_debug_suggest_signatures_json_includes_prototype_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            static void helper(int value) {}

            void caller_fn(int value)
            {
                helper(value);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-type-mismatch"},
            "target_asm": [
                "/* 0000 */ extsb r3, r31",
                "/* 0004 */ bl helper",
            ],
            "current_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
            ],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    action = report["findings"][0]["actions"][0]
    assert action["kind"] == "same-tu-static-prototype-candidate"
    assert action["candidate"]["proposed_type"] == "s8"
    assert action["candidate"]["expected_bank"] == "GPR"
    assert action["candidate"]["current_bank"] == "GPR"
    assert action["candidate"]["candidate_source"] == "prep-width"
    assert "decision_reason" in action["candidate"]
    assert action["patch"]["old"] == "int value"


def test_debug_suggest_signatures_json_includes_local_return_width_variant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            u8 helper(int idx);
            void sink(u8 value);

            void caller_fn(int idx)
            {
                u8 value;
                value = helper(idx);
                sink(value);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-return-width"},
            "target_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ mr r30, r3",
            ],
            "current_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ clrlwi r30, r3, 24",
            ],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    action = report["findings"][0]["actions"][0]
    assert action["kind"] == "call-site-local-return-width"
    assert action["source_variant"]["label"] == "local-temp-widen-consumer-cast"
    assert action["candidate"]["kind"] == "call-site-local-return-width"
    assert report["summary"]["local_return_width_candidate_count"] == 1


def test_signature_sibling_functions_infers_same_file_helper_callers() -> None:
    source = textwrap.dedent(
        """\
        u8 helper(int idx);

        void caller_fn(int idx)
        {
            value = helper(idx);
        }

        void sibling_a(int idx)
        {
            other = helper(idx);
        }

        void unrelated(int idx)
        {
            other = different(idx);
        }
        """
    )
    report = SimpleNamespace(
        findings=[
            SimpleNamespace(
                actions=[
                    SimpleNamespace(
                        kind="call-site-local-return-width",
                        candidate={"helper": "helper"},
                        source_variant=None,
                    )
                ]
            )
        ]
    )

    siblings = debug_cli._signature_sibling_functions(
        function="caller_fn",
        source_text=source,
        explicit_siblings=[],
        report=report,
    )

    assert siblings == ["sibling_a"]


def test_signature_scoreable_siblings_drop_missing_report_entries() -> None:
    siblings = debug_cli._signature_scoreable_sibling_functions(
        ["ranked_name", "missing_report", "unscored_but_runnable"],
        {
            "ranked_name": 97.5,
            "unscored_but_runnable": None,
        },
    )

    assert siblings == ["ranked_name", "unscored_but_runnable"]


def test_debug_suggest_signatures_text_prints_candidate_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            static void helper(int value) {}

            void caller_fn(int value)
            {
                helper(value);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-type-mismatch"},
            "target_asm": [
                "/* 0000 */ extsb r3, r31",
                "/* 0004 */ bl helper",
            ],
            "current_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
            ],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        "candidate: prototype-parameter-type int -> s8 "
        "(same-translation-unit, generated)"
    ) in result.output
    assert (
        "source=prep-width, expected_bank=GPR, current_bank=GPR"
    ) in result.output


def test_debug_suggest_signatures_json_includes_rebucket_prototype_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            void helper(void* obj);

            void caller_fn(void* obj)
            {
                helper(obj);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-type-mismatch"},
            "target_asm": ["/* 0000 */ bl helper"],
            "current_asm": ["/* 0000 */ bl helper"],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    action = report["findings"][0]["actions"][0]
    context = action["rebucket"]["prototype_context"]
    assert context["current_type"] == "void*"
    assert context["proposed_type"] is None
    assert context["current_bank"] == "GPR"
    assert context["expected_bank"] == "GPR"


def test_debug_suggest_signatures_text_prints_rebucket_prototype_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            void helper(void* obj);

            void caller_fn(void* obj)
            {
                helper(obj);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-type-mismatch"},
            "target_asm": ["/* 0000 */ bl helper"],
            "current_asm": ["/* 0000 */ bl helper"],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        "rebucket: prototype-already-matches-abi-bank -> "
        "signature-call-type/argument-presence"
    ) in result.output
    assert "prototype: void* -> no-change (GPR -> GPR)" in result.output


def test_debug_suggest_signatures_rejects_wrong_checkdiff_function(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void caller_fn(int value) { helper(value); }\n")
    payload_path = tmp_path / "wrong-checkdiff.json"
    payload_path.write_text(json.dumps({
        "function": "other_fn",
        "target_asm": [],
        "current_asm": [],
    }))
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "checkdiff JSON function mismatch" in result.output


def test_signature_candidate_checkdiff_restores_build_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void caller_fn(void) {}\n")
    build_obj = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    build_obj.parent.mkdir(parents=True)
    build_obj.write_bytes(b"original-object")
    lock_events: list[str] = []
    captured_dump_cmd: list[str] = []

    @contextmanager
    def fake_lock(root, *, label="checkdiff build/report"):
        lock_events.append(f"enter:{label}")
        yield
        lock_events.append(f"exit:{label}")

    def fake_run(cmd, **kwargs):
        cmd_list = [str(part) for part in cmd]
        if "debug" in cmd_list and "dump" in cmd_list and "local" in cmd_list:
            captured_dump_cmd[:] = cmd_list
            keep_obj = Path(cmd_list[cmd_list.index("--keep-obj") + 1])
            keep_obj.parent.mkdir(parents=True, exist_ok=True)
            keep_obj.write_bytes(b"candidate-object")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "checkdiff.py" in " ".join(cmd_list):
            assert build_obj.read_bytes() == b"candidate-object"
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({
                    "match": False,
                    "fuzzy_match_percent": 98.0,
                }),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd_list}")

    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = debug_cli._run_signature_candidate_checkdiff(
        function="caller_fn",
        candidate_source="void caller_fn(void) {}\n",
        source_path=source,
        unit="melee/demo",
        melee_root=melee_root,
        timeout=5.0,
    )

    assert result["fuzzy_match_percent"] == 98.0
    assert build_obj.read_bytes() == b"original-object"
    assert lock_events == [
        "enter:signature-audit validation",
        "exit:signature-audit validation",
    ]
    probe_source = Path(captured_dump_cmd[captured_dump_cmd.index("local") + 1])
    assert probe_source.is_relative_to(
        melee_root / "build" / "mwcc_debug_cache" / "probes" / "signature_audit"
    )


def test_signature_candidate_checkdiff_many_restores_build_object_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void caller_fn(void) {}\n")
    build_obj = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    build_obj.parent.mkdir(parents=True)
    build_obj.write_bytes(b"original-object")
    lock_events: list[str] = []
    dump_count = 0
    checked_functions: list[str] = []

    @contextmanager
    def fake_lock(root, *, label="checkdiff build/report"):
        lock_events.append(f"enter:{label}")
        yield
        lock_events.append(f"exit:{label}")

    def fake_run(cmd, **kwargs):
        nonlocal dump_count
        cmd_list = [str(part) for part in cmd]
        if "debug" in cmd_list and "dump" in cmd_list and "local" in cmd_list:
            dump_count += 1
            keep_obj = Path(cmd_list[cmd_list.index("--keep-obj") + 1])
            keep_obj.parent.mkdir(parents=True, exist_ok=True)
            keep_obj.write_bytes(b"candidate-object")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "checkdiff.py" in " ".join(cmd_list):
            assert build_obj.read_bytes() == b"candidate-object"
            checkdiff_index = next(
                i for i, part in enumerate(cmd_list) if part.endswith("checkdiff.py")
            )
            function = cmd_list[checkdiff_index + 1]
            checked_functions.append(function)
            score = 98.0 if function == "caller_fn" else 95.0
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({
                    "function": function,
                    "match": False,
                    "fuzzy_match_percent": score,
                }),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd_list}")

    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = debug_cli._run_signature_candidate_checkdiff_many(
        functions=["caller_fn", "sibling_fn"],
        candidate_source="void caller_fn(void) {}\n",
        source_path=source,
        unit="melee/demo",
        melee_root=melee_root,
        timeout=5.0,
    )

    assert result["caller_fn"]["fuzzy_match_percent"] == 98.0
    assert result["sibling_fn"]["fuzzy_match_percent"] == 95.0
    assert checked_functions == ["caller_fn", "sibling_fn"]
    assert dump_count == 1
    assert build_obj.read_bytes() == b"original-object"
    assert lock_events == [
        "enter:signature-audit validation",
        "exit:signature-audit validation",
    ]


def test_signature_candidate_checkdiff_many_build_restores_source_object_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    original_source = "void caller_fn(void) { original(); }\n"
    candidate_source = "void caller_fn(void) { candidate(); }\n"
    source.write_text(original_source)
    build_obj = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    build_obj.parent.mkdir(parents=True)
    build_obj.write_bytes(b"original-object")
    report_json = melee_root / "build" / "GALE01" / "report.json"
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_bytes(b'{"original": true}')
    lock_events: list[str] = []
    checked_functions: list[str] = []

    @contextmanager
    def fake_lock(root, *, label="checkdiff build/report"):
        lock_events.append(f"enter:{label}")
        yield
        lock_events.append(f"exit:{label}")

    def fake_run(cmd, **kwargs):
        cmd_list = [str(part) for part in cmd]
        if "checkdiff.py" in " ".join(cmd_list):
            assert "--no-build" not in cmd_list
            assert source.read_text() == candidate_source
            build_obj.write_bytes(b"candidate-object")
            report_json.write_bytes(b'{"candidate": true}')
            checkdiff_index = next(
                i for i, part in enumerate(cmd_list) if part.endswith("checkdiff.py")
            )
            function = cmd_list[checkdiff_index + 1]
            checked_functions.append(function)
            score = 98.0 if function == "caller_fn" else 95.0
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({
                    "function": function,
                    "match": False,
                    "fuzzy_match_percent": score,
                }),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd_list}")

    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = debug_cli._run_signature_candidate_checkdiff_many(
        functions=["caller_fn", "sibling_fn"],
        candidate_source=candidate_source,
        source_path=source,
        unit="melee/demo",
        melee_root=melee_root,
        timeout=5.0,
        rebuild_source=True,
    )

    assert result["caller_fn"]["fuzzy_match_percent"] == 98.0
    assert result["sibling_fn"]["fuzzy_match_percent"] == 95.0
    assert checked_functions == ["caller_fn", "sibling_fn"]
    assert source.read_text() == original_source
    assert build_obj.read_bytes() == b"original-object"
    assert report_json.read_bytes() == b'{"original": true}'
    assert lock_events == [
        "enter:signature-audit validation",
        "exit:signature-audit validation",
    ]


def test_signature_candidate_checkdiff_many_build_uses_repo_unit_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    override_source = tmp_path / "override.c"
    repo_source = melee_root / "src" / "melee" / "demo.c"
    repo_source.parent.mkdir(parents=True)
    original_source = "void caller_fn(void) { original(); }\n"
    candidate_source = "void caller_fn(void) { candidate(); }\n"
    override_source.write_text("void caller_fn(void) { override(); }\n")
    repo_source.write_text(original_source)

    @contextmanager
    def fake_lock(root, *, label="checkdiff build/report"):
        yield

    def fake_run(cmd, **kwargs):
        cmd_list = [str(part) for part in cmd]
        if "checkdiff.py" in " ".join(cmd_list):
            assert override_source.read_text() != candidate_source
            assert repo_source.read_text() == candidate_source
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout=json.dumps({
                    "function": "caller_fn",
                    "match": False,
                    "fuzzy_match_percent": 98.0,
                }),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd_list}")

    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = debug_cli._run_signature_candidate_checkdiff_many(
        functions=["caller_fn"],
        candidate_source=candidate_source,
        source_path=override_source,
        unit="melee/demo",
        melee_root=melee_root,
        timeout=5.0,
        rebuild_source=True,
    )

    assert result["caller_fn"]["fuzzy_match_percent"] == 98.0
    assert override_source.read_text() == "void caller_fn(void) { override(); }\n"
    assert repo_source.read_text() == original_source


def test_signature_candidate_checkdiff_many_build_passes_bounded_build_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void caller_fn(void) {}\n")
    captured_cmd: list[str] = []

    @contextmanager
    def fake_lock(root, *, label="checkdiff build/report"):
        yield

    def fake_run(cmd, **kwargs):
        captured_cmd[:] = [str(part) for part in cmd]
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout=json.dumps({
                "function": "caller_fn",
                "match": False,
                "fuzzy_match_percent": 98.0,
            }),
            stderr="",
        )

    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    debug_cli._run_signature_candidate_checkdiff_many(
        functions=["caller_fn"],
        candidate_source="void caller_fn(void) { candidate(); }\n",
        source_path=source,
        unit="melee/demo",
        melee_root=melee_root,
        timeout=5.0,
        rebuild_source=True,
    )

    assert "--build-timeout" in captured_cmd
    build_timeout = float(captured_cmd[captured_cmd.index("--build-timeout") + 1])
    assert 0 < build_timeout < 5.0


def test_signature_candidate_checkdiff_many_build_attempts_all_restores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void caller_fn(void) { original(); }\n")
    build_obj = melee_root / "build" / "GALE01" / "src" / "melee" / "demo.o"
    build_obj.parent.mkdir(parents=True)
    build_obj.write_bytes(b"original-object")
    report_json = melee_root / "build" / "GALE01" / "report.json"
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_bytes(b"original-report")

    @contextmanager
    def fake_lock(root, *, label="checkdiff build/report"):
        yield

    def fake_run(cmd, **kwargs):
        build_obj.write_bytes(b"candidate-object")
        report_json.write_bytes(b"candidate-report")
        raise RuntimeError("candidate failed")

    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)
    original_write_text = Path.write_text

    def flaky_write_text(self, *args, **kwargs):
        if self == source and args and "original" in str(args[0]):
            raise OSError("source restore failed")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    with pytest.raises(RuntimeError) as excinfo:
        debug_cli._run_signature_candidate_checkdiff_many(
            functions=["caller_fn"],
            candidate_source="void caller_fn(void) { candidate(); }\n",
            source_path=source,
            unit="melee/demo",
            melee_root=melee_root,
            timeout=5.0,
            rebuild_source=True,
        )

    assert "candidate failed" in str(excinfo.value)
    assert any(
        "failed to restore signature validation state" in note
        and "source restore failed" in note
        for note in getattr(excinfo.value, "__notes__", [])
    )
    assert build_obj.read_bytes() == b"original-object"
    assert report_json.read_bytes() == b"original-report"


def test_debug_suggest_signatures_build_validate_uses_rebuild_scoring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            u8 helper(int idx);
            void sink(u8 value);

            void caller_fn(int idx)
            {
                u8 value;
                value = helper(idx);
                sink(value);
            }
            """
        ),
        encoding="utf-8",
    )
    payload_path = tmp_path / "checkdiff.json"
    payload_path.write_text(
        json.dumps({
            "function": "caller_fn",
            "classification": {"primary": "signature-return-width"},
            "target_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ mr r30, r3",
            ],
            "current_asm": [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl helper",
                "/* 0008 */ clrlwi r30, r3, 24",
            ],
            "fuzzy_match_percent": 97.5,
        }),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_many(**kwargs):
        captured.update(kwargs)
        return {
            "caller_fn": {
                "function": "caller_fn",
                "match": False,
                "fuzzy_match_percent": 97.5,
            },
        }

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )
    monkeypatch.setattr(debug_cli, "_signature_sibling_functions", lambda **kwargs: [])
    monkeypatch.setattr(debug_cli, "_run_signature_candidate_checkdiff_many", fake_many)

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "suggest",
            "signatures",
            "-f",
            "caller_fn",
            "--checkdiff-json",
            str(payload_path),
            "--build",
            "--validate",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["rebuild_source"] is True
    report = json.loads(result.output)
    validation = report["findings"][0]["actions"][0]["validation"]
    assert validation["primary"]["status"] == "non-improving"
    assert validation["primary"]["candidate_match_percent"] == 97.5


def test_signature_sibling_baselines_skip_missing_report_functions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: None if function == "missing_fn" else "melee/demo",
    )

    def fake_read(**kwargs):
        calls.append(kwargs["function"])
        return {"fuzzy_match_percent": 95.0}, "fixture"

    monkeypatch.setattr(debug_cli, "_read_signature_checkdiff_payload", fake_read)

    baselines = debug_cli._signature_sibling_baselines(
        sibling_functions=["missing_fn", "sibling_fn"],
        melee_root=tmp_path,
        checkdiff_timeout=5.0,
    )

    assert calls == ["sibling_fn"]
    assert baselines == {"sibling_fn": 95.0}


def _consumer_home_call(symbol: str, offset: int, call_offset: int) -> list[str]:
    return [
        f"/* {call_offset:04X} */ addi r3, r1, 0x{offset:X}",
        f"/* {call_offset + 4:04X} */ bl {symbol}",
        f"/* {call_offset + 4:04X} */ R_PPC_REL24 {symbol}",
    ]


def _control_flow_shape_buffer_lifetime_payload() -> dict:
    payload = _control_flow_shape_checkdiff_payload()
    payload["target_asm"] = (
        _consumer_home_call("fn_803AC168", 0x120, 0)
        + _consumer_home_call("fn_803AC168", 0x148, 0x10)
        + _consumer_home_call("fn_803AC168", 0x170, 0x20)
    )
    payload["current_asm"] = (
        _consumer_home_call("fn_803AC168", 0x110, 0)
        + _consumer_home_call("fn_803AC168", 0x110, 0x10)
        + _consumer_home_call("fn_803AC168", 0x138, 0x20)
    )
    return payload


def test_debug_suggest_control_flow_shape_json_uses_checkdiff_without_pcdump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_reader(**kwargs):
        assert kwargs["function"] == "fn_80000000"
        return _control_flow_shape_checkdiff_payload(), "fixture-checkdiff"

    def fail_pcdump(*args, **kwargs):
        raise AssertionError("control-flow-shape suggest must not use pcdumps")

    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        fake_reader,
        raising=False,
    )
    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fail_pcdump)

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["function"] == "fn_80000000"
    assert payload["checkdiff_source"] == "fixture-checkdiff"
    assert payload["classification"]["primary"] == "control-flow-source-shape"
    assert [item["kind"] for item in payload["suggestions"]][:2] == [
        "branch-idiom",
        "pointer-walk-indexed-shape",
    ]


def test_debug_suggest_control_flow_shape_text_renders_ranked_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (_control_flow_shape_checkdiff_payload(), "fixture"),
        raising=False,
    )

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000"],
    )

    assert result.exit_code == 0, result.output
    output = strip_ansi(result.output)
    assert "control-flow-shape suggestions - fn_80000000" in output
    assert "#1 branch-idiom" in output
    assert "explicit if/else" in output
    assert "pointer-walk-indexed-shape" in output


def test_debug_suggest_control_flow_shape_json_reports_buffer_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (
            _control_flow_shape_buffer_lifetime_payload(),
            "fixture",
        ),
        raising=False,
    )

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    kinds = [item["kind"] for item in payload["suggestions"]]
    assert "concurrent-buffer-lifetime" in kinds
    suggestion = next(
        item
        for item in payload["suggestions"]
        if item["kind"] == "concurrent-buffer-lifetime"
    )
    assert suggestion["evidence"]["consumer_symbol"] == "fn_803AC168"
    assert all(
        "frame-transform" not in command
        for command in suggestion["follow_up_commands"]
    )


def test_debug_suggest_control_flow_shape_text_reports_buffer_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (
            _control_flow_shape_buffer_lifetime_payload(),
            "fixture",
        ),
        raising=False,
    )

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000"],
    )

    assert result.exit_code == 0, result.output
    output = strip_ansi(result.output)
    assert "concurrent-buffer-lifetime" in output
    assert "concurrently live" in output
    assert "fn_803AC168" in output


def test_debug_suggest_control_flow_shape_preflights_source_materialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _control_flow_shape_checkdiff_payload()
    payload["target_asm"] = [
        "/* 0000 */ lwz r4, 0(r3)",
        "/* 0004 */ addi r3, r3, 0x24",
        "/* 0008 */ lwz r4, 0(r3)",
        "/* 000C */ addi r3, r3, 0x24",
        "/* 0010 */ mtctr r5",
        "/* 0014 */ lwz r4, 0(r3)",
        "/* 0018 */ bdnz lbl_loop",
    ]
    payload["current_asm"] = [
        "/* 0000 */ mtctr r5",
        "/* 0004 */ lwz r4, 0(r3)",
        "/* 0008 */ bdnz lbl_loop",
    ]
    source = tmp_path / "src" / "melee" / "mn" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """
            void fn_80000000(void)
            {
                int x;
                x = 0;
            }
            """
        )
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (payload, "fixture"),
        raising=False,
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/mn/demo",
    )

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000", "--json"],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    suggestion = next(
        item
        for item in report["suggestions"]
        if item["kind"] == "loop-peel-unroll"
    )
    assert report["source_preflight"]["status"] == "ran"
    assert suggestion["follow_up_commands"] == []
    assert suggestion["source_materialization"]["status"] == "non-materializable"
    assert suggestion["source_materialization"]["operator"] == "loop-init"


def test_debug_suggest_control_flow_shape_rejects_wrong_function_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (
            _control_flow_shape_checkdiff_payload("fn_80000004"),
            "fixture",
        ),
        raising=False,
    )

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000"],
    )

    assert result.exit_code == 2
    assert "checkdiff JSON function fn_80000004 did not match fn_80000000" in (
        result.output
    )


def test_debug_suggest_control_flow_shape_rejects_missing_asm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _control_flow_shape_checkdiff_payload()
    del payload["current_asm"]
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (payload, "fixture"),
        raising=False,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "control-flow-shape",
            "-f",
            "fn_80000000",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert "checkdiff JSON did not include current_asm lines" in result.output


def test_debug_suggest_control_flow_shape_top_clips_ranked_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        debug_cli,
        "_read_control_flow_shape_checkdiff_payload",
        lambda **kwargs: (_control_flow_shape_buffer_lifetime_payload(), "fixture"),
        raising=False,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "control-flow-shape",
            "-f",
            "fn_80000000",
            "--json",
            "--top",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["suggestions"]) == 1
    assert payload["suggestions"][0]["rank"] == 1
    assert payload["suggestions"][0]["kind"] == "pointer-walk-indexed-shape"


def test_debug_suggest_control_flow_shape_reads_checkdiff_json_fixture(
    tmp_path: Path,
) -> None:
    checkdiff_json = tmp_path / "checkdiff.json"
    checkdiff_json.write_text(
        json.dumps(
            {
                **_control_flow_shape_checkdiff_payload(),
                "diff": ["representative checkdiff payload includes extra keys"],
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "control-flow-shape",
            "-f",
            "fn_80000000",
            "--json",
            "--checkdiff-json",
            str(checkdiff_json),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["checkdiff_source"] == str(checkdiff_json)
    assert payload["suggestions"][0]["kind"] == "branch-idiom"


def test_debug_suggest_control_flow_shape_rejects_malformed_checkdiff_json(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text("{not-json")

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "control-flow-shape",
            "-f",
            "fn_80000000",
            "--checkdiff-json",
            str(malformed),
        ],
    )

    assert result.exit_code == 2
    assert "checkdiff JSON could not be parsed" in result.output


def test_debug_suggest_control_flow_shape_rejects_non_object_checkdiff_json(
    tmp_path: Path,
) -> None:
    non_object = tmp_path / "list.json"
    non_object.write_text("[]")

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "control-flow-shape",
            "-f",
            "fn_80000000",
            "--checkdiff-json",
            str(non_object),
        ],
    )

    assert result.exit_code == 2
    assert "checkdiff JSON root was not an object" in result.output


def test_debug_suggest_control_flow_shape_reports_checkdiff_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "control-flow-shape",
            "-f",
            "fn_80000000",
            "--checkdiff-timeout",
            "0.01",
        ],
    )

    assert result.exit_code == 3
    assert "checkdiff timed out after 0.01s" in result.output


def test_debug_suggest_control_flow_shape_reports_checkdiff_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="compile failed\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        ["debug", "suggest", "control-flow-shape", "-f", "fn_80000000"],
    )

    assert result.exit_code == 2
    assert "compile failed" in result.output


def test_name_magic_source_declarations_help_is_available() -> None:
    result = runner.invoke(
        app,
        ["debug", "mutate", "name-magic-source-declarations", "--help"],
    )

    assert result.exit_code == 0
    assert "--score-match-percent" in result.output
    assert "--no-score-match-percent" in result.output
    assert "--compile-probes" in result.output


def test_name_magic_source_declarations_json_blocks_without_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.cli import debug as debug_cli

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: None,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["function"] == "fn_80000000"
    assert payload["blocker"] == "source-unavailable"
    assert payload["evidence"] == {}
    assert payload["stop_condition"]["kind"] == "blocked"


def test_name_magic_source_declarations_json_blocks_when_current_object_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+010: R_PPC_EMB_SDA21\tmn_804DBDA8",
                    "++010: R_PPC_EMB_SDA21\t@267",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "current-object-missing"
    assert payload["stop_condition"]["kind"] == "blocked"


def test_name_magic_source_declarations_json_blocks_when_target_object_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+010: R_PPC_EMB_SDA21\tmn_804DBDA8",
                    "++010: R_PPC_EMB_SDA21\t@267",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "target-object-missing"
    assert payload["stop_condition"]["kind"] == "blocked"


def test_name_magic_source_declarations_json_blocks_when_no_name_magic_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    source = tmp_path / "demo.c"
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            None,
            "checkdiff --no-name-magic emitted non-json",
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "no-name-magic-validation-failed"
    assert payload["stop_condition"]["kind"] == "blocked"


def test_name_magic_source_declarations_json_reports_sdata2_pool_order_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) { sink(0.0F); }\n", encoding="utf-8")
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+010: R_PPC_EMB_SDA21\tmn_804DBDA8",
                    "++010: R_PPC_EMB_SDA21\tlbl_804D0000",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {
                "anonymous_sdata2": {
                    "@267": {"size": 4, "float": 0.0, "value": 0}
                },
                "name_magic_suggestions": [],
            },
            None,
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "sdata2-pool-order-dependent"
    assert payload["stop_condition"]["kind"] == "blocked"


def test_name_magic_source_declarations_candidate_requires_no_name_magic_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    source = tmp_path / "candidate.c"
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+010: R_PPC_EMB_SDA21\tmn_804DBDA8",
                    "++010: R_PPC_EMB_SDA21\t@267",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {
                "anonymous_sdata2": {
                    "@267": {"size": 4, "float": 0.0, "value": 0}
                },
                "name_magic_suggestions": [
                    {
                        "anonymous": "@267",
                        "size": 4,
                        "value": 0,
                        "target": "mn_804DBDA8",
                    }
                ],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        lambda *args, **kwargs: debug_cli._NameMagicWholeSourceScore(
            100.0,
            None,
            False,
            {"match": False, "fuzzy_match_percent": 100.0},
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--candidate",
            f"manual:sdata2-named-float-load={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["variants"][0]["final_match_percent"] == 100.0
    assert payload["variants"][0]["no_name_magic_match"] is False
    assert payload["blocker"] == "no-name-magic-candidate"
    assert payload["stop_condition"] == {
        "kind": "unvalidated",
        "blocker": "no-name-magic-candidate",
        "reason": "no source candidate reached a true --no-name-magic match",
    }


def test_name_magic_source_declarations_reports_section_anchor_partial_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            static u16 mn_803EAE68[] = { 1, 2, 3 };

            void fn_80000000(void)
            {
                sink(mn_803EAE68);
                sink_float(0.0F);
                sink_float(0.0F);
            }
            """
        ),
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")
    initial_payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
            "-+02c: R_PPC_ADDR16_LO\tmn_803EAE68",
            "++02c: R_PPC_ADDR16_LO\t...data.0",
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    after_payload = {
        "match": False,
        "diff": [
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
        "fuzzy_match_percent": 99.99866,
    }
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (initial_payload, None),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {
                "anonymous_sdata2": {
                    "@267": {"size": 4, "float": 0.0, "value": 0}
                },
                "name_magic_suggestions": [],
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        lambda *args, **kwargs: debug_cli._NameMagicWholeSourceScore(
            99.99866,
            None,
            False,
            after_payload,
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "section-anchor-source-fixable-residual"
    assert payload["stop_condition"] == {
        "kind": "blocked",
        "blocker": "section-anchor-source-fixable-residual",
        "reason": (
            "section-anchor relocations were source-fixable, but residual "
            "no-name-magic mismatch remains"
        ),
    }
    assert payload["section_anchor_verdict"] == {
        "status": "source-fixable",
        "candidate_label": "data-symbol-static-to-global-0",
        "operator": "data-symbol-static-to-global",
        "resolved_offsets": ["024", "02c"],
        "remaining_offsets": [],
    }


def test_name_magic_source_declarations_reports_unsupported_bss_source_site(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            void fn_80181C80(void)
            {
                sink();
            }
            """
        ),
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")
    initial_payload = {
        "diff": [
            "-+004: R_PPC_ADDR16_HA\tlbl_80472ED8",
            "++004: R_PPC_ADDR16_HA\t...bss.0",
            "-+014: R_PPC_ADDR16_LO\tlbl_80472ED8",
            "++014: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {
            "primary": "instruction-sequence",
            "bss_anchor_relocations": {"status": "ceiling"},
        },
    }
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (initial_payload, None),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {"anonymous_sdata2": {}, "name_magic_suggestions": []},
            None,
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80181C80",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "unsupported-source-site"
    assert payload["stop_condition"] == {
        "kind": "blocked",
        "blocker": "unsupported-source-site",
        "reason": "unsupported-source-site",
    }
    assert payload["evidence"]["raw_relocations"] == [
        {
            "offset": "004",
            "kind": "R_PPC_ADDR16_HA",
            "expected_symbol": "lbl_80472ED8",
            "current_symbol": "...bss.0",
            "operator_family": "bss-anchor-ceiling",
        },
        {
            "offset": "014",
            "kind": "R_PPC_ADDR16_LO",
            "expected_symbol": "lbl_80472ED8",
            "current_symbol": "...bss.0",
            "operator_family": "bss-anchor-ceiling",
        },
    ]


def test_name_magic_source_declarations_scores_generated_bss_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        (
            "DemoBss mnDiagram_804A0750;\n"
            "void fn_80000000(void) { sink(&mnDiagram_804A0750); }\n"
        ),
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
                    "++038: R_PPC_ADDR16_LO\t...bss.0",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {"anonymous_sdata2": {}, "name_magic_suggestions": []},
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        lambda *args, **kwargs: debug_cli._NameMagicWholeSourceScore(
            92.70412,
            None,
            False,
            {"match": False, "fuzzy_match_percent": 92.70412},
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["probe_count"] == 1
    assert payload["blocker"] == "no-name-magic-candidate"
    assert payload["stop_condition"]["kind"] == "unvalidated"
    assert payload["probes"][0]["operator"] == "bss-anchor-source-binding"
    assert payload["variants"][0]["operator"] == "bss-anchor-source-binding"
    assert payload["variants"][0]["final_match_percent"] == 92.70412


def test_name_magic_source_declarations_bss_binding_is_not_validated_fix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        (
            "DemoBss mnDiagram_804A0750;\n"
            "void fn_80000000(void) { sink(&mnDiagram_804A0750); }\n"
        ),
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
                    "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
                    "++038: R_PPC_ADDR16_LO\t...bss.0",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {"anonymous_sdata2": {}, "name_magic_suggestions": []},
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        lambda *args, **kwargs: debug_cli._NameMagicWholeSourceScore(
            100.0,
            None,
            True,
            {"match": True, "fuzzy_match_percent": 100.0},
        ),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "no-name-magic-candidate"
    assert payload["stop_condition"]["kind"] == "unvalidated"
    assert payload["variants"][0]["operator"] == "bss-anchor-source-binding"
    assert payload["variants"][0]["no_name_magic_match"] is True


def test_name_magic_source_declarations_retains_header_externs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.cli import debug as debug_cli

    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    header = repo / "src" / "melee" / "demo.h"
    source.parent.mkdir(parents=True)
    source.write_text(
        '#include "demo.h"\n\nvoid fn_80000000(void) { sink(0.0F); }\n',
        encoding="utf-8",
    )
    header.write_text(
        "#ifndef DEMO_H\n#define DEMO_H\n\n#endif\n",
        encoding="utf-8",
    )
    current_obj = repo / "build" / "GALE01" / "src" / "melee" / "demo.o"
    target_obj = repo / "build" / "GALE01" / "obj" / "melee" / "demo.o"
    current_obj.parent.mkdir(parents=True)
    target_obj.parent.mkdir(parents=True)
    current_obj.write_bytes(b"fake")
    target_obj.write_bytes(b"fake")
    scored_headers: list[Path | None] = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", repo)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: (
            {
                "diff": [
                    "-+010: R_PPC_EMB_SDA21\tmn_804DBDA8",
                    "++010: R_PPC_EMB_SDA21\t@267",
                ],
                "classification": {"primary": "data-symbol-or-relocation"},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_name_magic_object_evidence",
        lambda unit, melee_root: (
            {
                "anonymous_sdata2": {
                    "@267": {"size": 4, "float": 0.0, "value": 0}
                },
                "name_magic_suggestions": [
                    {
                        "anonymous": "@267",
                        "size": 4,
                        "value": 0,
                        "target": "mn_804DBDA8",
                    }
                ],
            },
            None,
        ),
    )

    def fake_score(*args, **kwargs):
        scored_headers.append(kwargs.get("header_path"))
        return debug_cli._NameMagicWholeSourceScore(
            100.0,
            None,
            True,
            {"match": True},
        )

    monkeypatch.setattr(
        debug_cli,
        "_score_whole_source_candidate_no_name_magic",
        fake_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "name-magic-source-declarations",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    variant = payload["variants"][0]
    source_text = Path(variant["source_retained"]).read_text(encoding="utf-8")
    header_text = Path(variant["header_retained"]).read_text(encoding="utf-8")
    assert "extern volatile f32 mn_804DBDA8;" not in source_text
    assert "sink(mn_804DBDA8);" in source_text
    assert "extern volatile f32 mn_804DBDA8;" in header_text
    assert scored_headers == [Path(variant["header_retained"])]


def test_name_magic_whole_source_score_validates_cleanup_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { real_call(); }\n"
    source.write_text(original, encoding="utf-8")
    candidate = tmp_path / "candidate.c"
    candidate.write_text(
        "void fn_80000000(void) { candidate_call(); }\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, melee_root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_ninja_with_no_diag_retry",
        lambda *args, **kwargs: (
            subprocess.CompletedProcess(["ninja"], 0, "", ""),
            False,
        ),
    )
    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        lambda *args, **kwargs: (100.0, None),
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_checkdiff_no_name_magic_json",
        lambda *args, **kwargs: ({"match": True}, None),
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            "",
            "cleanup failed",
        ),
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        debug_cli._score_whole_source_candidate_no_name_magic(
            candidate,
            function="fn_80000000",
            melee_root=repo,
            timeout=1,
        )

    assert source.read_text(encoding="utf-8") == original


def test_indexed_struct_search_json_reports_no_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_unit_for_function", lambda function, root: None)

    result = runner.invoke(
        debug_cli.debug_app,
        ["mutate", "indexed-struct-search", "-f", "fn_80000000", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "source-unavailable"
    assert payload["function"] == "fn_80000000"
    assert payload["source"] is None
    assert payload["generated_source_dir"] is None
    assert payload["probe_count"] == 0
    assert payload["probes"] == []
    assert payload["stop_condition"] == {
        "kind": "blocked",
        "blocker": "source-unavailable",
        "reason": "source file could not be resolved",
    }
    assert payload["variants"] == []


def test_indexed_struct_search_json_scores_generated_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        textwrap.dedent(
            """\
            typedef struct Item {
                int x;
                int y;
            } Item;

            int fn_80000000(Item* items, int i)
            {
                Item* item = &items[i];
                int x = item->x;
                return item->y + x;
            }
            """
        )
    )
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_checkdiff_hint",
        lambda function, *, melee_root, timeout: {
            "expected_indexed_ops": [{"opcode": "lwzx"}],
            "current_materialized_pointers": [{"pointer_register": "r4"}],
        },
    )

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return "pcdump text"

    def fake_score(
        path,
        *,
        function,
        melee_root,
        timeout=None,
        status=None,
        include_stack_slot=False,
    ):
        return debug_cli._SourceCandidateRealScore(100.0, None)

    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fake_score,
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--json",
            "--max-probes",
            "4",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] is None
    assert payload["function"] == "fn_80000000"
    assert payload["source"].endswith("src/melee/demo.c")
    assert Path(payload["generated_source_dir"]).exists()
    assert payload["stop_condition"]["kind"] == "validated"
    assert payload["stop_condition"]["blocker"] is None
    assert payload["probe_count"] == 1
    assert payload["probes"][0]["operator"] == "indexed-struct-pointer"
    variant = payload["variants"][0]
    assert variant["status"] == "ok"
    assert variant["operator"] == "indexed-struct-pointer"
    assert Path(variant["path"]).exists()
    assert variant["match_percent"] == 100.0
    assert variant["final_match_percent"] == 100.0
    assert variant["error"] is None
    assert Path(variant["source_retained"]).exists()
    assert variant["probe"]["provenance"]["pointer"] == "item"
    assert variant["probe"]["provenance"]["kind"] == "indexed-struct-pointer"
    assert variant["probe"]["provenance"]["source_lines"] == [8, 10]


def test_indexed_struct_search_json_reports_missing_checkdiff_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "demo.c"
    source.write_text(
        textwrap.dedent(
            """\
            typedef struct Item {
                int x;
            } Item;

            int fn_80000000(Item* items, int i)
            {
                Item* item = &items[i];
                return item->x;
            }
            """
        )
    )
    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_checkdiff_hint",
        lambda function, *, melee_root, timeout: None,
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "indexed-struct-hint-unavailable"
    assert payload["blocker"] == payload["stop_condition"]["blocker"]
    assert payload["function"] == "fn_80000000"
    assert payload["source"] == str(source)
    assert payload["probe_count"] == 0
    assert payload["probes"] == []
    assert payload["stop_condition"]["kind"] == "blocked"
    assert payload["variants"] == []


def test_indexed_struct_search_json_reports_unmapped_hint_when_no_supported_initializer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "demo.c"
    source.write_text(
        textwrap.dedent(
            """\
            typedef struct Item {
                int x;
            } Item;

            int fn_80000000(Item* items, int i)
            {
                Item item = items[i];
                return item.x;
            }
            """
        )
    )
    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_checkdiff_hint",
        lambda function, *, melee_root, timeout: {
            "expected_indexed_ops": [{"opcode": "lwzx"}],
        },
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "indexed-struct-hint-unavailable"
    assert payload["blocker"] == payload["stop_condition"]["blocker"]
    assert payload["stop_condition"]["kind"] == "blocked"
    assert payload["probe_count"] == 0
    assert payload["probes"] == []
    assert payload["variants"] == []


def test_indexed_struct_search_json_reports_no_safe_materialized_pointer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "demo.c"
    source.write_text(
        textwrap.dedent(
            """\
            typedef struct Item {
                int x;
            } Item;

            int fn_80000000(Item* items, int i)
            {
                Item* item = &items[i];
                sink(item);
                return item->x;
            }
            """
        )
    )
    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_checkdiff_hint",
        lambda function, *, melee_root, timeout: {
            "expected_indexed_ops": [{"opcode": "lwzx"}],
        },
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "no-safe-materialized-pointer"
    assert payload["blocker"] == payload["stop_condition"]["blocker"]
    assert payload["stop_condition"]["kind"] == "blocked"
    assert payload["probe_count"] == 0
    assert payload["probes"] == []
    assert payload["variants"] == []


def test_indexed_struct_search_json_reports_unvalidated_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "candidate.c"
    source.write_text("int fn_80000000(void) { return 1; }\n")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return "pcdump text"

    def fake_score(
        path,
        *,
        function,
        melee_root,
        timeout=None,
        status=None,
        include_stack_slot=False,
    ):
        return debug_cli._SourceCandidateRealScore(99.5, None)

    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fake_score,
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--candidate",
            f"manual:indexed-struct-pointer={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "no-indexed-struct-candidate"
    assert payload["blocker"] == payload["stop_condition"]["blocker"]
    assert payload["stop_condition"]["kind"] == "unvalidated"
    assert payload["variants"][0]["operator"] == "indexed-struct-pointer"
    assert payload["variants"][0]["path"] == str(source)
    assert payload["variants"][0]["error"] is None
    assert payload["variants"][0]["match_percent"] == 99.5


def test_indexed_struct_search_json_reports_build_failed_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.diff_capture import CompileFailure

    source = tmp_path / "candidate.c"
    source.write_text("int fn_80000000(void) { return 1; }\n")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)

    def fake_compile(diff_input, *, function, melee_root, timeout):
        raise CompileFailure(
            "candidate",
            ["compile"],
            "",
            "compiler diagnostic",
            1,
        )

    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--candidate",
            f"manual:indexed-struct-pointer={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["blocker"] == "no-indexed-struct-candidate"
    assert payload["blocker"] == payload["stop_condition"]["blocker"]
    variant = payload["variants"][0]
    assert variant["status"] == "build-failed"
    assert variant["operator"] == "indexed-struct-pointer"
    assert variant["path"] == str(source)
    assert "compiler diagnostic" in variant["error"]


def test_indexed_struct_search_json_ranks_validated_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "candidate_a.c"
    source_b = tmp_path / "candidate_b.c"
    source_a.write_text("int fn_80000000(void) { return 1; }\n")
    source_b.write_text("int fn_80000000(void) { return 2; }\n")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)

    def fake_compile(diff_input, *, function, melee_root, timeout):
        return "pcdump text"

    def fake_score(
        path,
        *,
        function,
        melee_root,
        timeout=None,
        status=None,
        include_stack_slot=False,
    ):
        if path == source_b:
            return debug_cli._SourceCandidateRealScore(100.0, None)
        return debug_cli._SourceCandidateRealScore(90.0, None)

    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(debug_cli, "_score_source_candidate_real_tree", fake_score)

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--candidate",
            f"slow:indexed-struct-pointer={source_a}",
            "--candidate",
            f"match:indexed-struct-pointer={source_b}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["stop_condition"]["kind"] == "validated"
    assert [variant["label"] for variant in payload["variants"]] == [
        "match",
        "slow",
    ]
    assert payload["variants"][0]["final_match_percent"] == 100.0


def test_indexed_struct_search_json_lists_safe_probes_as_unvalidated_when_not_compiled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "demo.c"
    source.write_text(
        textwrap.dedent(
            """\
            typedef struct Item {
                int x;
            } Item;

            int fn_80000000(Item* items, int i)
            {
                Item* item = &items[i];
                return item->x;
            }
            """
        )
    )
    monkeypatch.setattr(
        debug_cli,
        "_indexed_struct_checkdiff_hint",
        lambda function, *, melee_root, timeout: {
            "expected_indexed_ops": [{"opcode": "lwzx"}],
        },
    )

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["probe_count"] == 1
    assert payload["variants"] == []
    assert payload["blocker"] == "no-indexed-struct-candidate"
    assert payload["stop_condition"] == {
        "kind": "unvalidated",
        "blocker": "no-indexed-struct-candidate",
        "reason": "safe indexed-struct probes were generated but not compiled",
    }


def test_indexed_struct_search_rejects_non_indexed_manual_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "candidate.c"
    source.write_text("int fn_80000000(void) { return 1; }\n")
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)

    result = runner.invoke(
        debug_cli.debug_app,
        [
            "mutate",
            "indexed-struct-search",
            "-f",
            "fn_80000000",
            "--candidate",
            f"manual:frame-transform={source}",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "expected indexed-struct-pointer candidate" in result.output


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
    trace = payload["current"]["frame_allocation_trace"]
    assert trace["status"] == "computed"
    assert trace["allocator_pass_status"] == "not-located"
    assert "reconstructed from final pcdump/asm r1 offsets" in (
        trace["allocator_pass_status_reason"]
    )
    assert trace["validation"]["frame_size_matches"] is True
    assert "objects" in trace
    assert "no current pcode stack access" in payload["summary"]


def test_frame_reservations_cli_text_reports_allocation_trace(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu r1,-56(r1)
            stw r8,24(r1)
            stmw r28,40(r1)
            addi r1,r1,56
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
            "--no-expected",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "frame allocation trace: computed" in result.stdout
    assert "allocator pass: not-located" in result.stdout
    assert (
        "frame allocation validation: frame-size ok, full-layout ok, "
        "non-overlap ok, r1-access coverage ok"
        in result.stdout
    )


def test_frame_reservations_missing_function_lists_small_dump_symbols(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function mnDiagram3_80245BA4
        Starting function mnDiagram3_80246D40
        Starting function fn_80246E04
        Starting function fn_80246E64
        Starting function fn_80246F0C
        Starting function mnDiagram3_80246F2C
        Starting function mnDiagram3_80247008
        Starting function mnDiagram3_8024714C
        Starting function fn_802461BC
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "mnDiagram3_HandleInput",
            str(pcdump),
            "--no-expected",
        ],
    )

    assert result.exit_code == 3
    assert "function 'mnDiagram3_HandleInput' not found in pcdump" in result.stderr
    assert "Functions in this dump:" in result.stderr
    assert "fn_802461BC" in result.stderr
    assert "semantic alias" in result.stderr


def test_suggest_frame_missing_function_lists_small_dump_symbols(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function mnDiagram3_80245BA4
        Starting function mnDiagram3_80246D40
        Starting function fn_80246E04
        Starting function fn_80246E64
        Starting function fn_80246F0C
        Starting function mnDiagram3_80246F2C
        Starting function mnDiagram3_80247008
        Starting function mnDiagram3_8024714C
        Starting function fn_802461BC
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "suggest",
            "frame",
            "-f",
            "mnDiagram3_HandleInput",
            str(pcdump),
            "--no-expected",
        ],
    )

    assert result.exit_code == 3
    assert "function 'mnDiagram3_HandleInput' not found in pcdump" in result.stderr
    assert "Functions in this dump:" in result.stderr
    assert "fn_802461BC" in result.stderr
    assert "semantic alias" in result.stderr


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


def test_inspect_analyze_reports_fpr_virtuals(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fpr_fn
        AFTER PEEPHOLE FORWARD
        fpr_fn
        B0: Succ={} Pred={} Labels={L0 }
            lfs f32,0(r3)
            fmuls f33,f32,f32
            stfs f33,0(r4)
        AFTER REGISTER COLORING
        fpr_fn
        B0: Succ={} Pred={} Labels={L0 }
            lfs f0,0(r3)
            fmuls f31,f0,f0
            stfs f31,0(r4)
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "analyze",
            str(pcdump),
            "-f",
            "fpr_fn",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [
        (item["reg_kind"], item["virtual"], item["physical"])
        for item in payload["virtuals"]
    ] == [("f", 32, 0), ("f", 33, 31)]


def test_inspect_simulate_reports_fpr_only_unsupported(tmp_path: Path) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fpr_fn
        AFTER PEEPHOLE FORWARD
        fpr_fn
        B0: Succ={} Pred={} Labels={L0 }
            lfs f32,0(r3)
            fmuls f33,f32,f32
            stfs f33,0(r4)
        AFTER REGISTER COLORING
        fpr_fn
        B0: Succ={} Pred={} Labels={L0 }
            lfs f0,0(r3)
            fmuls f31,f0,f0
            stfs f31,0(r4)
    """))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "simulate",
            str(pcdump),
            "-f",
            "fpr_fn",
        ],
    )

    assert result.exit_code == 0
    assert "FPR virtual registers found, but simulate is GPR-only" in result.stdout


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
        /* 80000000 */    stwu r1, -72(r1)
        /* 80000004 */    stfs f4, 40(r1)
        /* 80000008 */    stfs f5, 52(r1)
        /* 8000000c */    stfs f6, 48(r1)
        /* 80000010 */    addi r1, r1, 72
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
                "objective": {
                    "frame_after": 80,
                    "frame_delta": 0,
                },
                "stack_slot_localizer": {
                    "mismatch_count": 0,
                    "mismatches": [],
                },
            },
            {
                "label": "frame-shrink",
                "operator": "frame-magic-scratch-relocation",
                "status": "ok",
                "match_percent": 99.95,
                "objective": {
                    "frame_after": 72,
                    "frame_delta": -8,
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
    guidance = payload["current"]["stack_home_reorder_guidance"]
    assert guidance["validated_verdict"] == {
        "status": "source-reachable-reorder",
        "confidence": "high",
        "probe_verdict": "source-reachable-reorder",
        "reason": (
            "stack-home probe evidence validates a source-reachable reorder"
        ),
        "stop_condition": evaluation["stop_condition"],
    }
    frame_evaluation = payload["frame_transform_probe_evaluation"]
    assert frame_evaluation["verdict"] == "source-reachable-frame-transform"
    assert frame_evaluation["stop_condition"]["kind"] == "validated-frame-transform"
    assert frame_evaluation["best_variant"]["label"] == "frame-shrink"
    assert payload["frame_first_divergence"]["validated_verdict"] == {
        "status": "source-reachable-validated",
        "confidence": "high",
        "probe_verdict": "source-reachable-frame-transform",
        "reason": (
            "frame transform probe evidence validates a source-reachable "
            "change for the first frame divergence"
        ),
        "stop_condition": frame_evaluation["stop_condition"],
    }


def test_frame_reservations_cli_preserves_no_safe_semantic_status_from_probe_json(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000005
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000005
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stw     r8,48(r1)
            addi    r1,r1,80
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000005, global
        /* 80000000 */    stwu r1, -72(r1)
        /* 80000004 */    stw r8, 40(r1)
        /* 80000008 */    addi r1, r1, 72
        .endfn fn_80000005
    """))
    probe_results = tmp_path / "frame-transform-search.json"
    probe_results.write_text(json.dumps({
        "semantic_lever_status": {
            "status": "no-safe-semantic-lever",
            "operator": "frame-local-dematerialize",
            "reason": "source scan found no safe semantic local dematerialization",
        },
        "variants": [],
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000005",
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
    assert payload["semantic_lever_status"]["status"] == "no-safe-semantic-lever"
    evaluation = payload["frame_transform_probe_evaluation"]
    assert evaluation["verdict"] == "no-safe-semantic-lever"
    assert evaluation["stop_condition"]["kind"] == "no-safe-semantic-lever"


def test_frame_reservations_cli_ceiling_with_source_object_is_frame_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000003
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000003
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,a(r1)
            addi    r1,r1,80
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000003, global
        /* 80000000 */    stwu r1, -72(r1)
        /* 80000004 */    stfs f4, 40(r1)
        /* 80000008 */    addi r1, r1, 72
        .endfn fn_80000003
    """))
    probe_results = tmp_path / "probes.json"
    probe_results.write_text(json.dumps({
        "variants": [
            {
                "label": "unchanged",
                "operator": "block-scope",
                "status": "ok",
                "objective": {"frame_after": 80},
            }
        ]
    }))
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: 38 21 00 50 \taddi    r1,r1,80
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
            "fn_80000003",
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
    assert payload["frame_transform_probe_evaluation"]["verdict"] == (
        "frame-transform-results-inconclusive"
    )
    assert payload["frame_transform_probe_evaluation"]["stop_condition"]["kind"] == (
        "frame-transform-results-inconclusive"
    )
    assert payload["frame_first_divergence"]["source_attribution"]["status"] == (
        "source-object-attributed"
    )
    assert "validated_verdict" not in payload["frame_first_divergence"]


def test_frame_reservations_cli_ceiling_without_source_object_is_internal(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000004
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000004
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stw     r8,48(r1)
            addi    r1,r1,80
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000004, global
        /* 80000000 */    stwu r1, -72(r1)
        /* 80000004 */    stw r8, 40(r1)
        /* 80000008 */    addi r1, r1, 72
        .endfn fn_80000004
    """))
    probe_results = tmp_path / "probes.json"
    probe_results.write_text(json.dumps({
        "variants": [
            {
                "label": "unchanged",
                "operator": "block-scope",
                "status": "ok",
                "objective": {"frame_after": 80},
            }
        ]
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "frame-reservations",
            "-f",
            "fn_80000004",
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
    assert payload["frame_transform_probe_evaluation"]["verdict"] == (
        "frame-transform-results-inconclusive"
    )
    assert payload["frame_transform_probe_evaluation"]["stop_condition"]["kind"] == (
        "frame-transform-results-inconclusive"
    )
    assert payload["frame_first_divergence"]["source_attribution"]["status"] == (
        "unattributed"
    )
    assert "validated_verdict" not in payload["frame_first_divergence"]


def test_frame_reservations_cli_text_reports_primary_source_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80000005
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000005
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-80(r1)
            stfs    f4,a(r1)
            addi    r1,r1,80
    """))
    expected = tmp_path / "expected.s"
    expected.write_text(textwrap.dedent("""\
        .fn fn_80000005, global
        /* 80000000 */    stwu r1, -72(r1)
        /* 80000004 */    stfs f4, 40(r1)
        /* 80000008 */    addi r1, r1, 72
        .endfn fn_80000005
    """))
    current_asm = textwrap.dedent("""\
        +000: 94 21 ff b0 \tstwu    r1,-80(r1)
        +004: d0 81 00 30 \tstfs    f4,48(r1)
        +008: 38 21 00 50 \taddi    r1,r1,80
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
            "fn_80000005",
            str(pcdump),
            "--expected-asm",
            str(expected),
        ],
    )

    assert result.exit_code == 0, result.stdout
    out = strip_ansi(result.stdout)
    assert "cause: lifetime-or-ordering-shift (medium)" in out
    assert "source object: a (medium, local-or-temporary, 0x30->0x28)" in out


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
    assert "frame pass timeline: 1 pass(es)" in result.stdout
    assert "cause: stack-object-offset-shift (medium)" in result.stdout
    assert (
        "frame probe operators: frame-local-dematerialize, "
        "declaration-use-distance, block-scope, "
        "frame-direct-literal-at-final-fp-call, frame-split-fp-const-lifetime"
    ) in result.stdout
    assert (
        "next frame probe: melee-agent debug suggest frame -f gm_801A9DD0 --json"
    ) in result.stdout
    assert "source object: unattributed (mwcc-stack-home-origin-tags)" in result.stdout
    assert "verdict: unresolved-source-attribution" in result.stdout
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


def test_remote_pcdump_script_syncs_detached_default_checkout() -> None:
    script = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "mwcc_debug"
        / "win"
        / "run_pcdump.ps1"
    ).read_text()

    assert re.search(
        r'\$syncBranch\s+= if \(\$branch\) \{ \$branch \} else \{ "master" \}',
        script,
    )
    assert "git branch --show-current" in script
    assert "default checkout is detached" in script
    assert "git fetch origin $syncBranch" in script
    assert 'git reset --hard "origin/$syncBranch"' in script
    assert "git pull --rebase --autostash" in script


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


def test_permuter_bootstrap_injects_same_tu_callees_missing_from_target_calls() -> None:
    source_text = textwrap.dedent(
        """\
        int helper_inline(int value)
        {
            return value + 1;
        }

        int helper_called(int value)
        {
            return value + 2;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value) + helper_called(value);
        }
        """
    )
    base_text = textwrap.dedent(
        """\
        int helper_inline(int value);
        int helper_called(int value);

        int fn_80000000(int value)
        {
            return helper_inline(value) + helper_called(value);
        }
        """
    )
    target_asm = "\n".join([
        "<fn_80000000>:",
        "+024: 48 00 00 01 \tbl      helper_called",
        "+024: R_PPC_REL24\thelper_called",
    ])

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        target_asm,
    )

    assert injected == ["helper_inline"]
    assert "inline int helper_inline(int value)\n{\n    return value + 1;\n}" in patched
    assert "int helper_called(int value)\n{\n    return value + 2;\n}" not in patched
    assert patched.index("inline int helper_inline(int value)\n{") < patched.index(
        "int fn_80000000(int value)\n{"
    )


def test_permuter_bootstrap_moves_existing_callee_body_before_target() -> None:
    source_text = textwrap.dedent(
        """\
        int helper_inline(int value)
        {
            return value + 1;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )
    base_text = textwrap.dedent(
        """\
        int helper_inline(int value);

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }

        int helper_inline(int value)
        {
            return value + 1;
        }
        """
    )

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
    )

    assert injected == ["helper_inline"]
    assert patched.count("helper_inline(int value)\n{") == 1
    assert patched.index("inline int helper_inline(int value)\n{") < patched.index(
        "int fn_80000000(int value)\n{"
    )


def test_permuter_bootstrap_rewrites_existing_pre_target_body_inline() -> None:
    source_text = textwrap.dedent(
        """\
        int helper_inline(int value)
        {
            return value + 1;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )
    base_text = textwrap.dedent(
        """\
        int helper_inline(int value)
        {
            return value + 1;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
    )

    assert injected == ["helper_inline"]
    assert patched.count("helper_inline(int value)\n{") == 1
    assert "inline int helper_inline(int value)\n{" in patched
    assert patched.index("inline int helper_inline(int value)\n{") < patched.index(
        "int fn_80000000(int value)\n{"
    )


def test_permuter_bootstrap_orders_transitive_injected_callees_by_source() -> None:
    source_text = textwrap.dedent(
        """\
        int helper_leaf(int value)
        {
            return value + 1;
        }

        int helper_inline(int value)
        {
            return helper_leaf(value) + 1;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )
    base_text = textwrap.dedent(
        """\
        int helper_inline(int value);

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
    )

    assert injected == ["helper_inline", "helper_leaf"]
    assert patched.index("inline int helper_leaf(int value)\n{") < patched.index(
        "inline int helper_inline(int value)\n{"
    )
    assert patched.index("inline int helper_inline(int value)\n{") < patched.index(
        "int fn_80000000(int value)\n{"
    )


def test_permuter_bootstrap_keeps_callee_when_target_has_tail_branch() -> None:
    source_text = textwrap.dedent(
        """\
        int helper_tail(int value)
        {
            return value + 1;
        }

        int fn_80000000(int value)
        {
            return helper_tail(value);
        }
        """
    )
    base_text = textwrap.dedent(
        """\
        int helper_tail(int value);

        int fn_80000000(int value)
        {
            return helper_tail(value);
        }
        """
    )

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        "\n".join([
            "<fn_80000000>:",
            "+000: 48 00 00 00 \tb       helper_tail",
        ]),
    )

    assert injected == []
    assert patched == base_text


def test_permuter_bootstrap_injects_transitive_callee_when_direct_is_inline() -> None:
    source_text = textwrap.dedent(
        """\
        int helper_leaf(int value)
        {
            return value + 1;
        }

        inline int helper_inline(int value)
        {
            return helper_leaf(value) + 1;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )
    base_text = textwrap.dedent(
        """\
        int helper_leaf(int value);

        inline int helper_inline(int value)
        {
            return helper_leaf(value) + 1;
        }

        int fn_80000000(int value)
        {
            return helper_inline(value);
        }
        """
    )

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
    )

    assert injected == ["helper_inline", "helper_leaf"]
    assert patched.count("helper_inline(int value)\n{") == 1
    assert patched.count("helper_leaf(int value)\n{") == 1
    assert patched.index("inline int helper_leaf(int value)\n{") < patched.index(
        "inline int helper_inline(int value)\n{"
    )
    assert patched.index("inline int helper_inline(int value)\n{") < patched.index(
        "int fn_80000000(int value)\n{"
    )


def test_permuter_bootstrap_injects_callee_dependencies_missing_from_base() -> None:
    source_text = textwrap.dedent(
        """\
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram Diagram;

        void HSD_GObj_SetupProc(HSD_GObj* gobj, void (*proc)(HSD_GObj*), int prio);
        void* HSD_GObjGetUserData(HSD_GObj* gobj);
        void mnDiagram_CursorProc(HSD_GObj* gobj)
        {
        }

        void mnDiagram_80241730(HSD_GObj* arg0, int arg1, int arg2)
        {
            Diagram* data = GET_DIAGRAM(arg0);
            (void) data;
        }

        void mnDiagram_802433AC(void)
        {
            void** joint_data = mnDiagram_804A0814;
            HSD_GObj_SetupProc(0, mnDiagram_CursorProc, 0);
            (void) joint_data;
        }

        void fn_80000000(HSD_GObj* gobj)
        {
            mnDiagram_80241730(gobj, 1, 2);
            mnDiagram_802433AC();
        }
        """
    )
    dependency_text = textwrap.dedent(
        """\
        #define GET_DIAGRAM(gobj) ((Diagram*) HSD_GObjGetUserData(gobj))
        extern void* mnDiagram_804A0814[4];
        """
    )
    base_text = textwrap.dedent(
        """\
        typedef struct HSD_GObj HSD_GObj;
        typedef struct Diagram Diagram;
        void HSD_GObj_SetupProc(HSD_GObj* gobj, void (*proc)(HSD_GObj*), int prio);
        void* HSD_GObjGetUserData(HSD_GObj* gobj);
        void mnDiagram_80241730(HSD_GObj* arg0, int arg1, int arg2);
        void mnDiagram_802433AC(void);

        void fn_80000000(HSD_GObj* gobj)
        {
            mnDiagram_80241730(gobj, 1, 2);
            mnDiagram_802433AC();
        }
        """
    )

    patched, injected = debug_cli._inject_bootstrap_same_tu_inlined_callees(
        base_text,
        source_text,
        "fn_80000000",
        "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
        dependency_text=dependency_text,
    )

    assert injected == ["mnDiagram_80241730", "mnDiagram_802433AC"]
    assert "#define GET_DIAGRAM(gobj)" in patched
    assert "extern void* mnDiagram_804A0814[4];" in patched
    assert "void mnDiagram_CursorProc(HSD_GObj* gobj);" in patched
    assert patched.index("#define GET_DIAGRAM(gobj)") < patched.index(
        "inline void mnDiagram_80241730"
    )
    assert patched.index("extern void* mnDiagram_804A0814[4];") < patched.index(
        "inline void mnDiagram_802433AC"
    )
    assert patched.index("void mnDiagram_CursorProc(HSD_GObj* gobj);") < patched.index(
        "inline void mnDiagram_802433AC"
    )


def test_permuter_bootstrap_inline_definition_preserves_preprocessor_preamble() -> None:
    source = textwrap.dedent(
        """\
        #undef __FILE__
        #define __FILE__ "jobj.h"
        static void helper(void)
        {
        }
        """
    )

    result = debug_cli._bootstrap_inline_definition(source)

    assert "inline #undef" not in result
    assert result.startswith(
        '#undef __FILE__\n#define __FILE__ "jobj.h"\nstatic inline void helper'
    )


def test_permuter_bootstrap_sanitizes_raw_assert_macros_when_permuter_define_exists() -> None:
    base_text = textwrap.dedent(
        """\
        #pragma _permuter define HSD_ASSERT(line,cond) ((cond)?((void)0):__assert("<stdin>",line,#cond))
        void __assert(char*, unsigned int, char*);
        #define __FILE__ "jobj.h"
        #define HSD_ASSERT(line,cond) \\
            ((cond)?((void)0):__assert(__FILE__,line,#cond))
        #undef __FILE__
        #define __FILE__ "<stdin>"

        void fn_80000000(void* jobj)
        {
            HSD_ASSERT(932, jobj);
        }
        """
    )

    sanitized, changed = debug_cli._sanitize_bootstrap_assert_macros(base_text)

    assert changed is True
    assert "#pragma _permuter define HSD_ASSERT" in sanitized
    assert "#define HSD_ASSERT" not in sanitized
    assert "#define __FILE__" not in sanitized
    assert "#undef __FILE__" not in sanitized
    assert "HSD_ASSERT(932, jobj);" in sanitized


def test_permuter_bootstrap_keeps_raw_assert_macro_without_permuter_define() -> None:
    base_text = textwrap.dedent(
        """\
        #define HSD_ASSERT(line,cond) \\
            ((cond)?((void)0):__assert(__FILE__,line,#cond))

        void fn_80000000(void* jobj)
        {
            HSD_ASSERT(932, jobj);
        }
        """
    )

    sanitized, changed = debug_cli._sanitize_bootstrap_assert_macros(base_text)

    assert changed is False
    assert sanitized == base_text


def test_permuter_bootstrap_dependency_context_reads_angle_local_includes(
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "mndiagram3.c"
    include_path = melee_root / "src" / "sysdolphin" / "baselib" / "jobj.h"
    src_path.parent.mkdir(parents=True)
    include_path.parent.mkdir(parents=True)
    include_path.write_text("#define JOBJ_MTX_INDEP_SRT (1 << 25)\n")
    source_text = "#include <baselib/jobj.h>\n\nvoid fn(void) {}\n"

    dependency_text = debug_cli._bootstrap_dependency_context(
        source_text,
        source_path=src_path,
        melee_root=melee_root,
    )

    assert "#define JOBJ_MTX_INDEP_SRT" in dependency_text


def test_debug_permute_bootstrap_injects_same_tu_inlined_callee_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        textwrap.dedent(
            """\
            int helper_inline(int value)
            {
                return value + 1;
            }

            int fn_80000000(int value)
            {
                return helper_inline(value);
            }
            """
        ),
        encoding="utf-8",
    )
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        if "import.py" in argv[1]:
            fn_dir = perm_root / "nonmatchings" / "fn_80000000"
            fn_dir.mkdir(parents=True)
            (fn_dir / "base.c").write_text(
                textwrap.dedent(
                    """\
                    int helper_inline(int value);

                    int fn_80000000(int value)
                    {
                        return helper_inline(value);
                    }
                    """
                ),
                encoding="utf-8",
            )
            (fn_dir / "target.s").write_text(
                "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
                encoding="utf-8",
            )
            (fn_dir / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (fn_dir / "base.o").write_bytes(b"stale")
            (fn_dir / "target.o").write_bytes(b"target")
            (fn_dir / "settings.toml").write_text("stock = true\n", encoding="utf-8")
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
    assert payload["injected_inline_callees"] == ["helper_inline"]
    assert payload["invalidated_base_object"] is True
    assert payload["randomize_funcs"] == ["fn_80000000", "helper_inline"]
    assert payload["recommended_randomize_funcs"] == [
        "fn_80000000",
        "helper_inline",
    ]
    assert payload["randomize_funcs_status"] == "written"
    assert not (perm_root / "nonmatchings" / "fn_80000000" / "base.o").exists()
    base_text = (
        perm_root / "nonmatchings" / "fn_80000000" / "base.c"
    ).read_text(encoding="utf-8")
    assert "inline int helper_inline(int value)\n{\n    return value + 1;\n}" in base_text
    assert base_text.index("inline int helper_inline(int value)\n{") < base_text.index(
        "int fn_80000000(int value)\n{"
    )
    settings_text = (
        perm_root / "nonmatchings" / "fn_80000000" / "settings.toml"
    ).read_text(encoding="utf-8")
    assert 'randomize_funcs = ["fn_80000000", "helper_inline"]' in settings_text


def test_debug_permute_bootstrap_reports_kept_settings_randomize_funcs_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        textwrap.dedent(
            """\
            int helper_inline(int value)
            {
                return value + 1;
            }

            int fn_80000000(int value)
            {
                return helper_inline(value);
            }
            """
        ),
        encoding="utf-8",
    )
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")
    destination = perm_root / "nonmatchings" / "fn_80000000"
    destination.mkdir(parents=True)
    (destination / "settings.toml").write_text(
        textwrap.dedent(
            """\
            custom = true
            compiler_command = "/opt/devkitpro/devkitPPC/bin/mwcceppc.exe"
            assembler_command = "/opt/devkitpro/devkitPPC/bin/powerpc-eabi-as -mgekko"

            [weight_overrides]
            perm_reorder_decls = 77.0
            """
        ),
        encoding="utf-8",
    )

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        if "import.py" in argv[1]:
            imported = melee_root / "nonmatchings" / "fn_80000000-2"
            imported.mkdir(parents=True)
            (imported / "base.c").write_text(
                textwrap.dedent(
                    """\
                    int helper_inline(int value);

                    int fn_80000000(int value)
                    {
                        return helper_inline(value);
                    }
                    """
                ),
                encoding="utf-8",
            )
            (imported / "target.s").write_text(
                "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
                encoding="utf-8",
            )
            (imported / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (imported / "target.o").write_bytes(b"target")
            (imported / "settings.toml").write_text("stock = true\n", encoding="utf-8")
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
    assert payload["injected_inline_callees"] == ["helper_inline"]
    assert payload["randomize_funcs"] is None
    assert payload["recommended_randomize_funcs"] == [
        "fn_80000000",
        "helper_inline",
    ]
    assert payload["randomize_funcs_status"] == "existing-settings-kept"
    assert payload["settings"]["action"] == "repaired"
    settings_text = (destination / "settings.toml").read_text(encoding="utf-8")
    settings = tomllib.loads(settings_text)
    assert settings["custom"] is True
    assert settings["func_name"] == "fn_80000000"
    assert settings["objdump_command"] == "melee-agent debug target dtk-objdump"
    assert "compiler_command" not in settings
    assert "assembler_command" not in settings
    assert settings["weight_overrides"]["perm_reorder_decls"] == 77.0


def test_debug_permute_bootstrap_force_rewrites_randomize_funcs_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        textwrap.dedent(
            """\
            int helper_inline(int value)
            {
                return value + 1;
            }

            int fn_80000000(int value)
            {
                return helper_inline(value);
            }
            """
        ),
        encoding="utf-8",
    )
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")
    destination = perm_root / "nonmatchings" / "fn_80000000"
    destination.mkdir(parents=True)
    (destination / "settings.toml").write_text("custom = true\n", encoding="utf-8")

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        if "import.py" in argv[1]:
            imported = melee_root / "nonmatchings" / "fn_80000000-2"
            imported.mkdir(parents=True)
            (imported / "base.c").write_text(
                textwrap.dedent(
                    """\
                    int helper_inline(int value);

                    int fn_80000000(int value)
                    {
                        return helper_inline(value);
                    }
                    """
                ),
                encoding="utf-8",
            )
            (imported / "target.s").write_text(
                "<fn_80000000>:\n+000: 38 60 00 01 \tli      r3,1\n",
                encoding="utf-8",
            )
            (imported / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (imported / "target.o").write_bytes(b"target")
            (imported / "settings.toml").write_text("stock = true\n", encoding="utf-8")
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
            "--force",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["randomize_funcs"] == ["fn_80000000", "helper_inline"]
    assert payload["randomize_funcs_status"] == "written"
    settings_text = (destination / "settings.toml").read_text(encoding="utf-8")
    assert 'randomize_funcs = ["fn_80000000", "helper_inline"]' in settings_text


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
    settings = tomllib.loads((destination / "settings.toml").read_text())
    assert settings["custom"] is True
    assert settings["func_name"] == "fn_80000000"
    assert settings["objdump_command"] == "melee-agent debug target dtk-objdump"
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


def test_debug_permute_triage_without_apply_best_restores_winning_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void)\n{\n    real_call();\n}\n"
    src_path.write_text(original)

    perm_dir = tmp_path / "nonmatchings" / "fn_80000000"
    output_dir = perm_dir / "output-1535-1"
    output_dir.mkdir(parents=True)
    (output_dir / "source.c").write_text(
        "void fn_80000000(void)\n{\n    better_call();\n}\n"
    )

    pcts = iter([91.0, 91.25, 91.25])

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
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "WIN" in result.stdout
    assert src_path.read_text() == original


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
    assert "up to 1024 entries" in normalized
    assert "application logs are" in normalized
    assert "written into the pcdump" in normalized
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


def test_dump_local_function_scopes_explicit_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(void)\n{\n}\n"
        "void fn_80000001(void)\n{\n}\n"
        "void fn_80000002(void)\n{\n}\n"
    )
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        "pcdump.write_text("
        "'Starting function fn_80000000\\nfirst\\n'"
        "'Starting function fn_80000001\\ntarget\\n'"
        "'Starting function fn_80000002\\nlast\\n'"
        ")\n"
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
            "fn_80000001",
            "--output",
            str(output),
            "--no-cache-sync",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert output.read_text() == "Starting function fn_80000001\ntarget\n"


def test_dump_local_function_scoped_output_keeps_full_cache_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80000000(void)\n{\n}\n"
        "void fn_80000001(void)\n{\n}\n"
        "void fn_80000002(void)\n{\n}\n"
    )
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    full_dump = (
        "Starting function fn_80000000\nfirst\n"
        "Starting function fn_80000001\ntarget\n"
        "Starting function fn_80000002\nlast\n"
    )
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "from pathlib import Path\n"
        "pcdump = Path.cwd() / os.environ['MWCC_DEBUG_PCDUMP_PATH']\n"
        f"pcdump.write_text({full_dump!r})\n"
    )
    wibo.chmod(0o755)
    output = tmp_path / "pcdump.out"
    cache = melee_root / "build" / "mwcc_debug_cache" / "melee" / "mn" / "sample.txt"

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
            "fn_80000001",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert output.read_text() == "Starting function fn_80000001\ntarget\n"
    assert cache.read_text() == full_dump
    assert cache.with_suffix(".hash").exists()


def test_dump_local_forced_default_output_uses_managed_scratch_root(
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
    scratch_root = tmp_path / "mwcc-debug-tmp"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_cache_settle_seconds", lambda env=None: 0.0)
    monkeypatch.setenv("MWCC_DEBUG_TMP_ROOT", str(scratch_root))

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--force-phys",
            "1:4",
            "--force-phys-fn",
            "fn_80000000",
            "--function",
            "fn_80000000",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    match = re.search(r"Dump at: (.+)", result.stderr)
    assert match is not None
    output = Path(match.group(1).strip())
    assert output.parent == scratch_root
    assert output.name.startswith("pcdump_forced_")
    assert output.exists()


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


def test_dump_local_refuses_uninterruptible_matching_wibo_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.local_safety import LocalWiboProcess

    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "sysdolphin" / "baselib" / "particle.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void hsd_80391AC8(void)\n{\n}\n")
    compiler_dir = melee_root / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc_debug.exe").write_text("")
    wibo = tmp_path / "wibo"
    launched_marker = tmp_path / "wibo-launched"
    wibo.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(launched_marker)!r}).write_text('launched')\n"
    )
    wibo.chmod(0o755)
    unsafe = LocalWiboProcess(
        pid=80283,
        ppid=1,
        stat="UEs",
        elapsed="10:27",
        command=(
            "wibo mwcceppc_debug.exe "
            "-c src/sysdolphin/baselib/particle.c"
        ),
        source_rel="src/sysdolphin/baselib/particle.c",
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda src_rel: ("", "mwcc"))
    monkeypatch.setattr(
        debug_cli.local_safety,
        "scan_local_wibo_processes",
        lambda: [unsafe],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(src_path),
            "--function",
            "hsd_80391AC8",
            "--output",
            str(tmp_path / "pcdump.out"),
            "--no-cache-sync",
        ],
    )

    assert result.exit_code == 125
    assert "unsafe local pcdump lane" in result.stderr
    assert "80283" in result.stderr
    assert "src/sysdolphin/baselib/particle.c" in result.stderr
    assert not launched_marker.exists()


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


def test_inspect_explain_schedule_reads_checkdiff_json_for_addi_window(
    tmp_path: Path,
) -> None:
    pcdump = tmp_path / "pcdump.txt"
    pcdump.write_text(
        "Starting function it_802BCB88\n"
        "FINAL CODE AFTER INSTRUCTION SCHEDULING\n"
        "it_802BCB88\n"
        ":{0000}::::LOOPWEIGHT=0\n"
        "B0: Succ={} Pred={} Labels={}\n\n"
        "    addi    r3,r1,72\n"
        "    lfs     f0,108(r1)\n"
        "    addi    r28,r28,1\n"
    )
    checkdiff_json = tmp_path / "checkdiff.json"
    checkdiff_json.write_text(json.dumps({
        "function": "it_802BCB88",
        "classification": {
            "primary": "operand-register-or-offset",
            "reasons": [
                "opcode sequence matches; differences are operands, registers, "
                "labels, or offsets"
            ],
        },
        "target_asm": [
            "<it_802BCB88>:",
            "+1fc: 3b 9c 00 01 \taddi    r28,r28,1",
            "+200: c0 01 00 6c \tlfs     f0,108(r1)",
            "+204: 38 61 00 48 \taddi    r3,r1,72",
        ],
        "current_asm": [
            "<it_802BCB88>:",
            "+1fc: 38 61 00 48 \taddi    r3,r1,72",
            "+200: c0 01 00 6c \tlfs     f0,108(r1)",
            "+204: 3b 9c 00 01 \taddi    r28,r28,1",
        ],
    }))

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "explain-schedule",
            "--function",
            "it_802BCB88",
            "--pcdump",
            str(pcdump),
            "--checkdiff-json",
            str(checkdiff_json),
            "--force-schedule",
            "addi:0x204>0x1fc",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "status=matched" in result.stdout
    assert "window_kind=asm-code-offset" in result.stdout
    assert "source_shape_verdict=source-shape-controllable" in result.stdout
    assert "not-forceable-by-current-hook" in result.stdout


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


_TEST_DLL_FEATURE_MANIFEST = (
    "MWCC_DEBUG_FEATURES:v5;"
    "pcdump-path;"
    "function-scope-force-phys;"
    "force-phys-iter;"
    "force-phys-overflow-error;"
    "force-iter-first-overflow-error;"
    "force-remat;"
    "force-interfere;"
    "force-schedule;"
    "force-no-cse"
)


def _write_test_mwcc_debug_dll(path: Path, *, manifest: bool = True) -> None:
    payload = b"MZ" + (b"\0" * 4094)
    if manifest:
        payload += _TEST_DLL_FEATURE_MANIFEST.encode("ascii")
    path.write_bytes(payload)


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
    for filename in ("mwcceppc.exe", "mwcceppc_debug.exe"):
        (compiler_dir / filename).write_text("")
    _write_test_mwcc_debug_dll(compiler_dir / "MWDBG326.dll")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    for filename in (
        "build_wibo.sh",
        "build_macos.sh",
        "mwcc_debug.c",
        "patch_mwcceppc_for_wibo.py",
    ):
        (tools_dir / filename).write_text("")
    _write_test_mwcc_debug_dll(tools_dir / "MWDBG326.dll")
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


def test_debug_dump_doctor_reports_deployed_dll_missing_feature_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    for filename in ("mwcceppc.exe", "mwcceppc_debug.exe"):
        (compiler_dir / filename).write_text("")
    _write_test_mwcc_debug_dll(compiler_dir / "MWDBG326.dll", manifest=False)
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    for filename in (
        "build_wibo.sh",
        "build_macos.sh",
        "mwcc_debug.c",
        "patch_mwcceppc_for_wibo.py",
    ):
        (tools_dir / filename).write_text("")
    _write_test_mwcc_debug_dll(tools_dir / "MWDBG326.dll", manifest=False)
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

    assert result.exit_code == 2
    out = strip_ansi(result.stdout)
    assert "FAIL\tmwcc_debug DLL features" in out
    assert "MWCC_DEBUG_FEATURES" in out
    assert "melee-agent debug dump setup" in out


def test_debug_dump_doctor_reports_stale_dll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    for filename in ("mwcceppc.exe", "mwcceppc_debug.exe"):
        (compiler_dir / filename).write_text("")
    _write_test_mwcc_debug_dll(compiler_dir / "MWDBG326.dll")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    for filename in (
        "build_wibo.sh",
        "build_macos.sh",
        "patch_mwcceppc_for_wibo.py",
    ):
        (tools_dir / filename).write_text("")
    _write_test_mwcc_debug_dll(tools_dir / "MWDBG326.dll")
    source = tools_dir / "mwcc_debug.c"
    source.write_text("// newer source")
    stale_time = 1_000_000_000
    fresh_time = stale_time + 10
    for path in (tools_dir / "MWDBG326.dll", compiler_dir / "MWDBG326.dll"):
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
    monkeypatch.setattr(
        debug_cli,
        "_smoke_mwcc_debug_compiler",
        lambda *_args, **_kwargs: debug_cli._DumpSetupCheck(
            "mwcc_debug pcdump smoke",
            True,
            "pcdump smoke produced 1 byte",
        ),
    )
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
    monkeypatch.setattr(
        debug_cli,
        "_smoke_mwcc_debug_compiler",
        lambda *_args, **_kwargs: debug_cli._DumpSetupCheck(
            "mwcc_debug pcdump smoke",
            True,
            "pcdump smoke produced 1 byte",
        ),
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(app, ["debug", "dump", "setup"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (tools_dir / "MWDBG326.dll").read_text() == "built dll"
    assert patch_calls
    assert str(tools_dir / "MWDBG326.dll") in patch_calls[0]
    out = strip_ansi(result.stdout)
    assert "using alternate DLL output" in out


def test_debug_dump_setup_aborts_when_deployed_dll_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "build" / "compilers" / "GC" / "1.2.5n"
    compiler_dir.mkdir(parents=True)
    (compiler_dir / "mwcceppc.exe").write_text("stock compiler")
    tools_dir = tmp_path / "tools" / "mwcc_debug"
    tools_dir.mkdir(parents=True)
    dll = tools_dir / "MWDBG326.dll"
    dll.write_bytes(b"MZ" + b"\0" * 4096)
    source = tools_dir / "mwcc_debug.c"
    source.write_text("// source")
    for filename in ("build_wibo.sh", "build_macos.sh", "patch_mwcceppc_for_wibo.py"):
        (tools_dir / filename).write_text("")
    wibo = tools_dir / "bin" / "wibo"
    wibo.parent.mkdir(parents=True)
    wibo.write_text("")
    wibo.chmod(0o755)

    def fake_run(args: list[str], **_kwargs) -> SimpleNamespace:
        if "--dll" in args:
            (compiler_dir / "MWDBG326.dll").write_bytes(dll.read_bytes())
            (compiler_dir / "mwcceppc_debug.exe").write_text("patched compiler")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(
        debug_cli,
        "_smoke_mwcc_debug_compiler",
        lambda *_args, **_kwargs: debug_cli._DumpSetupCheck(
            "mwcc_debug pcdump smoke",
            False,
            "pcdump.txt missing or empty",
        ),
    )

    result = runner.invoke(app, ["debug", "dump", "setup"])

    assert result.exit_code == 7
    out = strip_ansi(result.stdout + result.stderr)
    assert "pcdump smoke failed" in out
    assert "pcdump.txt missing or empty" in out


def test_smoke_mwcc_debug_compiler_requires_nonempty_pcdump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    (compiler_dir / "mwcceppc_debug.exe").write_text("patched compiler")
    wibo = tmp_path / "wibo"
    wibo.write_text("")
    wibo.chmod(0o755)

    def fake_run(_args, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    check = debug_cli._smoke_mwcc_debug_compiler(wibo, compiler_dir)

    assert check.ok is False
    assert "missing or empty" in check.detail


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
    cli_cwd = tmp_path / "tools" / "melee-agent"
    cli_cwd.mkdir(parents=True)

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
    monkeypatch.chdir(cli_cwd)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(probe),
            "--unit-source",
            "src/melee/ft/ftdynamics.c",
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


def test_debug_dump_local_missing_unit_source_reports_resolution_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    probe = tmp_path / "build" / "mwcc_debug_cache" / "probes" / "e7b4" / "probe.c"
    probe.parent.mkdir(parents=True)
    probe.write_text("void ftCo_8009E7B4(void) {}\n")
    cli_cwd = tmp_path / "tools" / "melee-agent"
    cli_cwd.mkdir(parents=True)
    unit_arg = "src/melee/ft/ftdynamics.c"

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", tmp_path)
    monkeypatch.chdir(cli_cwd)

    result = runner.invoke(
        app,
        [
            "debug",
            "dump",
            "local",
            str(probe),
            "--unit-source",
            unit_arg,
            "--function",
            "ftCo_8009E7B4",
        ],
    )

    out = strip_ansi(result.stderr + result.stdout)
    assert result.exit_code == 2
    assert "unit source not found" in out
    assert unit_arg in out
    assert "cwd=" in out
    assert "repo=" in out
    assert "tried:" in out
    assert "tools/melee-agent" in out
    assert "src/melee/ft/ftdynamics.c" in out


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


def _write_divide_remat_diagnose_fixture(tmp_path: Path) -> tuple[Path, Path]:
    melee_root = tmp_path
    src_path = melee_root / "src" / "melee" / "gm" / "gm_1832.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(
        "void fn_80188910(void)\n"
        "{\n"
        "    if ((val / 100) != 0) {\n"
        "        HSD_JObjReqAnimAll(jobj, (f32) (val / 100));\n"
        "    }\n"
        "}\n"
    )
    asm_path = melee_root / "build" / "GALE01" / "asm" / "melee" / "gm" / "gm_1832.s"
    asm_path.parent.mkdir(parents=True)
    asm_path.write_text(textwrap.dedent("""\
        .fn fn_80188910, global
        /* 801889D4 001855B4  3C 60 51 EC */ lis r3, 0x51ec
        /* 801889DC 001855BC  38 03 85 1F */ subi r0, r3, 0x7ae1
        /* 801889E0 001855C0  7C 80 F8 96 */ mulhw r4, r0, r31
        /* 801889E4 001855C4  7C 80 2E 70 */ srawi r0, r4, 5
        /* 801889E8 001855C8  54 03 0F FE */ srwi r3, r0, 31
        /* 801889EC 001855CC  7C 00 1A 15 */ add. r0, r0, r3
        /* 801889F0 001855D0  41 82 00 38 */ beq .L_80188A28
        /* 801889F4 001855D4  7C 80 2E 70 */ srawi r0, r4, 5
        /* 801889FC 001855DC  54 04 0F FE */ srwi r4, r0, 31
        /* 80188A04 001855E4  7C 00 22 14 */ add r0, r0, r4
        /* 80188A08 001855E8  6C 00 80 00 */ xoris r0, r0, 0x8000
        .L_80188A28:
        /* 80188A30 00185610  48 1E 6E 8D */ bl HSD_JObjReqAnimAll
        .endfn fn_80188910
    """))
    pcdump = tmp_path / "gm_1832.pcdump.txt"
    pcdump.write_text(textwrap.dedent("""\
        Starting function fn_80188910
        BEFORE REGISTER COLORING
        fn_80188910
        B0: Succ={B1 B2} Pred={} Labels={}
            lis r32, 0x51ec
            subi r33, r32, 0x7ae1
            mulhw r60, r33, r31
            srawi r64, r60, 5
            srwi r62, r64, 31
            add r35, r64, r62
            bt eq B2
        B1: Succ={B3} Pred={B0} Labels={}
            xoris r65, r35, 0x8000
            b B3
        B2: Succ={B3} Pred={B0} Labels={}
            li r65, 0
        B3: Succ={} Pred={B1 B2} Labels={}
            blr
    """))
    return melee_root, pcdump


def test_diagnose_json_reports_divide_rematerialization_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root, pcdump = _write_divide_remat_diagnose_fixture(tmp_path)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/gm/gm_1832",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 94.89)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "fn_80188910",
            "--skip-decl-orders",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "INTRINSIC VALUE-NUMBERING CEILING"
    assert payload["value_numbering_ceiling"]["kind"] == (
        "signed-magic-divide-rematerialization"
    )
    assert payload["value_numbering_ceiling"]["source_lever_status"] == (
        "no-current-C-source-lever"
    )
    assert any("value-numbering ceiling" in item for item in payload["recommendations"])


def test_diagnose_text_reports_divide_rematerialization_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root, pcdump = _write_divide_remat_diagnose_fixture(tmp_path)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/gm/gm_1832",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 94.89)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "fn_80188910",
            "--skip-decl-orders",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "[!] Value-numbering ceiling:" in out
    assert "signed magic divide" in out
    assert "== VERDICT: INTRINSIC VALUE-NUMBERING CEILING ==" in out
    assert "== VERDICT: NO FAST TRANSFORM FOUND ==" not in out


def test_disp_form_rollback_hint_recommends_cached_base_and_per_loop_locals() -> None:
    source = textwrap.dedent("""\
        typedef struct CardBufEntry {
            int x10;
        } CardBufEntry;
        extern void* hsd_804D1138;

        void fn_803ADE4C(void)
        {
            CardBufEntry* entries = (CardBufEntry*) hsd_804D1138;
            int snap;
            int saved;

            while (snap != 0) {
                entries[saved].x10 = 0;
                saved = (saved + 1) % 128;
            }
            while (snap != 0) {
                entries[saved].x10 = 0;
                saved = (saved + 1) % 128;
            }
        }
    """)

    hint = debug_cli._detect_disp_form_rollback_hint(source, "fn_803ADE4C")

    assert hint is not None
    assert hint["kind"] == "disp-form-rollback-source-shape"
    assert hint["rollback_store_count"] == 2
    assert hint["inline_base_cast_hint"]["status"] == "recommended"
    assert hint["inline_base_cast_hint"]["cached_base_names"] == ["entries"]
    assert hint["per_loop_local_split_hint"]["status"] == "recommended"
    assert hint["per_loop_local_split_hint"]["shared_index_names"] == ["saved"]
    assert any("inline base cast" in item for item in hint["recommendations"])
    assert any("per-loop" in item for item in hint["recommendations"])


def test_disp_form_rollback_hint_ignores_non_loop_stores() -> None:
    source = textwrap.dedent("""\
        typedef struct CardBufEntry {
            int x10;
        } CardBufEntry;
        extern void* hsd_804D1138;

        void fn_803ADE4C(void)
        {
            CardBufEntry* entries = (CardBufEntry*) hsd_804D1138;
            int saved;

            entries[saved].x10 = 0;
        }
    """)

    assert debug_cli._detect_disp_form_rollback_hint(
        source,
        "fn_803ADE4C",
    ) is None


def test_disp_form_rollback_hint_requires_loop_carried_index_for_split() -> None:
    source = textwrap.dedent("""\
        typedef struct CardBufEntry {
            int x10;
        } CardBufEntry;
        extern void* hsd_804D1138;

        void fn_803ADE4C(void)
        {
            CardBufEntry* entries = (CardBufEntry*) hsd_804D1138;
            int snap;
            int saved;

            while (snap != 0) {
                entries[saved].x10 = 0;
                --snap;
            }
            while (snap != 0) {
                entries[saved].x10 = 0;
                --snap;
            }
        }
    """)

    hint = debug_cli._detect_disp_form_rollback_hint(source, "fn_803ADE4C")

    assert hint is not None
    assert hint["rollback_store_count"] == 2
    assert hint["inline_base_cast_hint"]["status"] == "recommended"
    assert hint["per_loop_local_split_hint"]["status"] == "not-needed"
    assert hint["per_loop_local_split_hint"]["shared_index_names"] == []
    assert not any("per-loop" in item for item in hint["recommendations"])


def test_disp_form_rollback_hint_marks_inlined_single_loop_without_split() -> None:
    source = textwrap.dedent("""\
        typedef struct CardBufEntry {
            int x10;
        } CardBufEntry;
        extern void* hsd_804D1138;

        void fn_803ADE4C(void)
        {
            int snap;
            int saved;

            while (snap != 0) {
                ((CardBufEntry*) hsd_804D1138)[saved].x10 = 0;
                saved = (saved + 1) % 128;
            }
        }
    """)

    hint = debug_cli._detect_disp_form_rollback_hint(source, "fn_803ADE4C")

    assert hint is not None
    assert hint["rollback_store_count"] == 1
    assert hint["inline_base_cast_hint"]["status"] == "already-applied"
    assert hint["per_loop_local_split_hint"]["status"] == "not-needed"
    assert not any("per-loop" in item for item in hint["recommendations"])


def _write_disp_form_rollback_diagnose_fixture(tmp_path: Path) -> tuple[Path, Path]:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "hsd" / "hsd_3AA7.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(textwrap.dedent("""\
        typedef struct CardBufEntry {
            int x10;
        } CardBufEntry;
        extern void* hsd_804D1138;

        void fn_803ADE4C(void)
        {
            CardBufEntry* entries = (CardBufEntry*) hsd_804D1138;
            int snap;
            int saved;

            while (snap != 0) {
                entries[saved].x10 = 0;
                saved = (saved + 1) % 128;
            }
            while (snap != 0) {
                entries[saved].x10 = 0;
                saved = (saved + 1) % 128;
            }
        }
    """))
    pcdump = tmp_path / "hsd_3AA7.pcdump.txt"
    pcdump.write_text("Starting function fn_803ADE4C\n")
    return melee_root, pcdump


def test_diagnose_json_reports_disp_form_rollback_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root, pcdump = _write_disp_form_rollback_diagnose_fixture(tmp_path)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/hsd/hsd_3AA7",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 96.10)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "fn_803ADE4C",
            "--skip-decl-orders",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["disp_form_rollback"]["kind"] == (
        "disp-form-rollback-source-shape"
    )
    assert payload["disp_form_rollback"]["inline_base_cast_hint"]["status"] == (
        "recommended"
    )
    assert payload["disp_form_rollback"]["per_loop_local_split_hint"]["status"] == (
        "recommended"
    )
    assert any("inline base cast" in item for item in payload["recommendations"])
    assert any("per-loop" in item for item in payload["recommendations"])


def test_diagnose_text_reports_disp_form_rollback_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root, pcdump = _write_disp_form_rollback_diagnose_fixture(tmp_path)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/hsd/hsd_3AA7",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 96.10)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "fn_803ADE4C",
            "--skip-decl-orders",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "[!] Disp-form rollback/source-shape hint:" in out
    assert "inline base cast" in out
    assert "per-loop" in out


def _pointer_reassoc_source() -> str:
    return textwrap.dedent("""\
        typedef struct CardState {
            unsigned char* x0;
        } CardState;

        void fn_803ACFC0(CardState* state, int hdr_offset, void* payload, int payload_size)
        {
            memcpy(state->x0 + hdr_offset + 0x20, payload, payload_size);
            fn_803AC3F8(state, state->x0 + hdr_offset + 0x13, 0);
            (state->x0 + hdr_offset)[0x10] = 1;
        }
    """)


def _pointer_reassoc_expected_asm() -> str:
    return textwrap.dedent("""\
        .fn fn_803ACFC0, global
        /* 803AD078 003A9C58  80 18 00 00 */ lwz r0, 0x0(r24)
        /* 803AD084 003A9C64  7C 7D 02 14 */ add r3, r29, r0
        /* 803AD088 003A9C68  38 63 00 20 */ addi r3, r3, 0x20
        /* 803AD08C 003A9C6C  4B C5 61 69 */ bl memcpy
        /* 803AD100 003A9CE0  80 18 00 00 */ lwz r0, 0x0(r24)
        /* 803AD104 003A9CE4  7C 9D 02 14 */ add r4, r29, r0
        /* 803AD108 003A9CE8  38 84 00 13 */ addi r4, r4, 0x13
        /* 803AD10C 003A9CEC  4B FF F2 ED */ bl fn_803AC3F8
        .endfn fn_803ACFC0

        .fn fn_803B1F78, global
        /* 803B2000 003AEBDC  7C 9F 22 14 */ add r4, r31, r4
        /* 803B2004 003AEBE0  38 84 00 20 */ addi r4, r4, 0x20
        /* 803B2008 003AEBE4  4B C5 61 69 */ bl memcpy
        .endfn fn_803B1F78
    """)


def _pointer_reassoc_current_pcdump() -> str:
    return textwrap.dedent("""\
        Starting function fn_803ACFC0
        BEFORE GLOBAL OPTIMIZATION
        fn_803ACFC0
            lwz     r61,0(r32); fIsPtrOp
            addi    r3,r43,32
            add     r3,r61,r3
            mr      r4,r36
            mr      r5,r37
            bl      memcpy; fLink
            mr      r3,r32
            lwz     r76,0(r32); fIsPtrOp
            addi    r4,r43,19
            add     r4,r76,r4
            mr      r5,r38
            bl      fn_803AC3F8; fLink
        Starting function fn_803B1F78
            addi    r3,r6,32
            add     r3,r31,r3
            bl      memcpy; fLink
    """)


def test_pointer_offset_reassociation_hint_requires_expected_and_current_shapes() -> None:
    hint = debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=_pointer_reassoc_expected_asm(),
        current_pcdump_text=_pointer_reassoc_current_pcdump(),
    )

    assert hint is not None
    assert hint["kind"] == "pointer-offset-constant-reassociation"
    assert hint["source_lever_status"] == (
        "expression-spelling-alone-not-actionable-from-current-diagnose"
    )
    assert [(site["consumer"], site["constant"]) for site in hint["sites"]] == [
        ("memcpy", 0x20),
        ("fn_803AC3F8", 0x13),
    ]
    assert all(site["subkind"] == "call-arg-split-add-addi" for site in hint["sites"])
    assert any("force-phys" in item for item in hint["recommendations"])


def test_pointer_offset_reassociation_hint_ignores_source_only_and_adjacent_asm() -> None:
    adjacent_only_expected = textwrap.dedent("""\
        .fn fn_803ACFC0, global
        /* 803AD08C 003A9C6C  4B C5 61 69 */ bl memcpy
        .endfn fn_803ACFC0
        .fn fn_803B1F78, global
        /* 803B2000 003AEBDC  7C 9F 22 14 */ add r3, r31, r4
        /* 803B2004 003AEBE0  38 63 00 20 */ addi r3, r3, 0x20
        /* 803B2008 003AEBE4  4B C5 61 69 */ bl memcpy
        .endfn fn_803B1F78
    """)

    assert debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=adjacent_only_expected,
        current_pcdump_text=_pointer_reassoc_current_pcdump(),
    ) is None
    assert debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=_pointer_reassoc_expected_asm(),
        current_pcdump_text="Starting function fn_803ACFC0\n    bl memcpy; fLink\n",
    ) is None


def test_pointer_offset_reassociation_hint_ignores_byte_displacement_stores() -> None:
    source = textwrap.dedent("""\
        typedef struct CardState {
            unsigned char* x0;
        } CardState;

        void fn_803ACFC0(CardState* state, int hdr_offset)
        {
            (state->x0 + hdr_offset)[0x10] = 1;
            (state->x0 + hdr_offset)[0x11] = 2;
            (state->x0 + hdr_offset)[0x12] = 3;
        }
    """)

    assert debug_cli._detect_pointer_offset_reassociation_hint(
        source,
        "fn_803ACFC0",
        expected_asm_text=_pointer_reassoc_expected_asm(),
        current_pcdump_text=_pointer_reassoc_current_pcdump(),
    ) is None


def test_pointer_offset_reassociation_hint_ignores_comments_and_strings() -> None:
    source = textwrap.dedent("""\
        typedef struct CardState {
            unsigned char* x0;
        } CardState;

        void fn_803ACFC0(CardState* state, int hdr_offset, void* payload, int payload_size)
        {
            /*
             * memcpy(state->x0 + hdr_offset + 0x20, payload, payload_size);
             */
            const char* trace = "fn_803AC3F8(state, state->x0 + hdr_offset + 0x13, 0)";
            memcpy(state->x0 + hdr_offset, payload, payload_size);
        }
    """)

    assert debug_cli._detect_pointer_offset_reassociation_hint(
        source,
        "fn_803ACFC0",
        expected_asm_text=_pointer_reassoc_expected_asm(),
        current_pcdump_text=_pointer_reassoc_current_pcdump(),
    ) is None


def test_pointer_offset_reassociation_hint_requires_arg_register_live_to_call() -> None:
    expected_with_clobber = textwrap.dedent("""\
        .fn fn_803ACFC0, global
        /* 803AD084 003A9C64  7C 7D 02 14 */ add r3, r29, r0
        /* 803AD088 003A9C68  38 63 00 20 */ addi r3, r3, 0x20
        /* 803AD08A 003A9C6A  7C 83 23 78 */ mr r3, r4
        /* 803AD08C 003A9C6C  4B C5 61 69 */ bl memcpy
        .endfn fn_803ACFC0
    """)
    current_with_clobber = textwrap.dedent("""\
        Starting function fn_803ACFC0
            addi    r3,r43,32
            add     r3,r61,r3
            mr      r3,r44
            bl      memcpy; fLink
    """)

    assert debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=expected_with_clobber,
        current_pcdump_text=_pointer_reassoc_current_pcdump(),
    ) is None
    assert debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=_pointer_reassoc_expected_asm(),
        current_pcdump_text=current_with_clobber,
    ) is None


def test_pointer_offset_reassociation_hint_requires_intermediate_register_live() -> None:
    expected_with_intermediate_clobber = textwrap.dedent("""\
        .fn fn_803ACFC0, global
        /* 803AD084 003A9C64  7D 1D 02 14 */ add r8, r29, r0
        /* 803AD086 003A9C66  7D 08 23 78 */ mr r8, r4
        /* 803AD088 003A9C68  38 68 00 20 */ addi r3, r8, 0x20
        /* 803AD08C 003A9C6C  4B C5 61 69 */ bl memcpy
        .endfn fn_803ACFC0
    """)
    current_with_intermediate_clobber = textwrap.dedent("""\
        Starting function fn_803ACFC0
            addi    r8,r43,32
            mr      r8,r44
            add     r3,r61,r8
            bl      memcpy; fLink
    """)

    assert debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=expected_with_intermediate_clobber,
        current_pcdump_text=_pointer_reassoc_current_pcdump(),
    ) is None
    assert debug_cli._detect_pointer_offset_reassociation_hint(
        _pointer_reassoc_source(),
        "fn_803ACFC0",
        expected_asm_text=_pointer_reassoc_expected_asm(),
        current_pcdump_text=current_with_intermediate_clobber,
    ) is None


def _write_pointer_reassoc_diagnose_fixture(tmp_path: Path) -> tuple[Path, Path]:
    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "hsd" / "hsd_3AA7.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(_pointer_reassoc_source())
    asm_path = melee_root / "build" / "GALE01" / "asm" / "melee" / "hsd" / "hsd_3AA7.s"
    asm_path.parent.mkdir(parents=True)
    asm_path.write_text(_pointer_reassoc_expected_asm())
    pcdump = tmp_path / "hsd_3AA7.pcdump.txt"
    pcdump.write_text(_pointer_reassoc_current_pcdump())
    return melee_root, pcdump


def test_diagnose_json_reports_pointer_offset_reassociation_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root, pcdump = _write_pointer_reassoc_diagnose_fixture(tmp_path)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/hsd/hsd_3AA7",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 90.63)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "fn_803ACFC0",
            "--skip-decl-orders",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["pointer_offset_reassociation"]["kind"] == (
        "pointer-offset-constant-reassociation"
    )
    assert [site["consumer"] for site in payload["pointer_offset_reassociation"]["sites"]] == [
        "memcpy",
        "fn_803AC3F8",
    ]
    assert any("pointer-offset reassociation" in item for item in payload["recommendations"])


def test_diagnose_text_reports_pointer_offset_reassociation_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root, pcdump = _write_pointer_reassoc_diagnose_fixture(tmp_path)

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/hsd/hsd_3AA7",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 90.63)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )

    result = runner.invoke(
        app,
        ["debug", "inspect", "diagnose", "fn_803ACFC0", "--skip-decl-orders"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "[!] Pointer-offset reassociation:" in out
    assert "memcpy +0x20" in out
    assert "fn_803AC3F8 +0x13" in out


def test_diagnose_pointer_offset_hint_does_not_preempt_verified_win(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.cast_audit import CastWarning

    melee_root, pcdump = _write_pointer_reassoc_diagnose_fixture(tmp_path)
    src_path = melee_root / "src" / "melee" / "hsd" / "hsd_3AA7.c"
    src_path.write_text(
        src_path.read_text().replace(
            "fn_803AC3F8(state, state->x0 + hdr_offset + 0x13, 0);",
            "OSReport(\"%f\", (f32) payload_size);\n"
            "    fn_803AC3F8(state, state->x0 + hdr_offset + 0x13, 0);",
        )
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/hsd/hsd_3AA7",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 90.63)
    monkeypatch.setattr(
        debug_cli,
        "audit_function_casts",
        lambda source, function: [
            CastWarning(
                line=6,
                call_target="OSReport",
                arg_index=1,
                cast_type="f32",
                inner_expr="payload_size",
                severity="high",
                reason="integer local cast to float in variadic call",
            )
        ],
    )
    monkeypatch.setattr(debug_cli, "_build_and_match", lambda unit, function, root: 91.0)
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "diagnose",
            "fn_803ACFC0",
            "--skip-decl-orders",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "WIN AVAILABLE"
    assert payload["pointer_offset_reassociation"] is not None
    assert payload["recommendations"][0].startswith("Drop 1 HIGH-severity cast")
    assert not payload["recommendations"][0].startswith("pointer-offset reassociation")


def test_diagnose_text_pointer_offset_hint_does_not_print_recommendation_for_verified_win(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.cast_audit import CastWarning

    melee_root, pcdump = _write_pointer_reassoc_diagnose_fixture(tmp_path)
    src_path = melee_root / "src" / "melee" / "hsd" / "hsd_3AA7.c"
    src_path.write_text(
        src_path.read_text().replace(
            "fn_803AC3F8(state, state->x0 + hdr_offset + 0x13, 0);",
            "OSReport(\"%f\", (f32) payload_size);\n"
            "    fn_803AC3F8(state, state->x0 + hdr_offset + 0x13, 0);",
        )
    )

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/hsd/hsd_3AA7",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 90.63)
    monkeypatch.setattr(
        debug_cli,
        "audit_function_casts",
        lambda source, function: [
            CastWarning(
                line=6,
                call_target="OSReport",
                arg_index=1,
                cast_type="f32",
                inner_expr="payload_size",
                severity="high",
                reason="integer local cast to float in variadic call",
            )
        ],
    )
    monkeypatch.setattr(debug_cli, "_build_and_match", lambda unit, function, root: 91.0)
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        ["debug", "inspect", "diagnose", "fn_803ACFC0", "--skip-decl-orders"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "[!] Pointer-offset reassociation:" in out
    assert "== VERDICT: WIN AVAILABLE ==" in out
    assert "Drop 1 HIGH-severity cast" in out
    assert "pointer-offset reassociation: stop cycling" not in out


def test_diagnose_noop_cast_verify_does_not_report_win_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.cast_audit import CastWarning

    melee_root = tmp_path / "melee"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text(textwrap.dedent("""\
        void fn_80000000(void)
        {
            int fighter_id;
            OSReport("%f", (f32) fighter_id);
        }
    """))
    pcdump = tmp_path / "sample.pcdump.txt"
    pcdump.write_text("Starting function fn_80000000\n")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 94.44)
    monkeypatch.setattr(
        debug_cli,
        "audit_function_casts",
        lambda source, function: [
            CastWarning(
                line=4,
                call_target="OSReport",
                arg_index=1,
                cast_type="f32",
                inner_expr="fighter_id",
                severity="high",
                reason="integer local cast to float in variadic call",
            )
        ],
    )
    monkeypatch.setattr(debug_cli, "_build_and_match", lambda unit, function, root: 94.44)
    monkeypatch.setattr(debug_cli, "_detect_frame_residual_hint", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        debug_cli,
        "_resolve_pcdump_path",
        lambda pcdump_arg, function, melee_root=None, *, require_fresh=False: pcdump,
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = runner.invoke(
        app,
        ["debug", "inspect", "diagnose", "fn_80000000", "--skip-decl-orders"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    out = strip_ansi(result.stdout)
    assert "(+0.00%, WIN)" not in out
    assert "(+0.00%, false positive)" in out
    assert "== VERDICT: NO FAST TRANSFORM FOUND ==" in out
    assert "== VERDICT: WIN AVAILABLE ==" not in out


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
                        "stack_frame_delta": {"missing_stack_bytes": 16},
                        "reasons": [
                            "frame reservation gap is too small; try frame transform"
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
    assert payload["frame_residual"]["cause"] == "pure-reservation"
    assert payload["frame_residual"]["closability_tier"] == "current-tools-padstack"
    assert payload["frame_residual"]["subcategory"] == "frame-too-small"
    assert payload["next_steps"][0] == (
        "melee-agent debug mutate frame-transform-search -f fn_80000000 "
        "--source-file src/melee/mn/sample.c "
        "--operator frame-reservation-pad-stack "
        "--frame-reservation-bytes 16 --compile-probes --json"
    )
    assert "debug inspect frame-reservations -f fn_80000000" in payload["next_steps"][1]
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
                        "stack_slot_localizer": {
                            "frame_size": 64,
                            "mismatch_count": 1,
                            "mismatches": [
                                {
                                    "expected_offset": 52,
                                    "current_offset": 48,
                                    "delta": 4,
                                    "opcode": "stfs",
                                }
                            ],
                        },
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
    assert payload["frame_residual"]["cause"] == "stack-object-offset-shift"
    assert payload["frame_residual"]["closability_tier"] == "reorder-gated-362"
    assert payload["frame_residual"]["match_relevance"] == "match-neutral"
    assert payload["next_steps"][0] == (
        "melee-agent debug mutate lifetime-layout -f fn_80000000 "
        "--source-file src/melee/mn/sample.c --compile-probes --json"
    )
    assert payload["next_steps"][1] == (
        "melee-agent debug inspect frame-reservations -f fn_80000000"
    )
    assert "match-neutral frame residual" in payload["frame_residual"]["message"]
    assert "stack-home assignment order" in payload["frame_residual"]["message"]
    assert "Optional cheap probe" in "\n".join(payload["next_steps"])


def test_inspect_stuck_routes_reserved_low_spill_to_ceiling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    src_path.parent.mkdir(parents=True)
    src_path.write_text("void fn_80000000(void) { int a; a = 0; }\n")

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "classification": {
                        "primary": "stack-slot-layout",
                        "stack_slot_localizer": {
                            "deltas": [12],
                            "reserved_low_spill_region": {
                                "kind": "reserved-unused-low-spill-region",
                                "closability_tier": "ceiling",
                            },
                        },
                        "reasons": [
                            "reserved-but-unused low spill region candidate"
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
    monkeypatch.setattr(debug_cli, "_get_match_pct", lambda function, root: 99.95)
    monkeypatch.setattr(debug_cli, "audit_function_casts", lambda source, function: [])
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        ["debug", "inspect", "stuck", "fn_80000000", "--no-pcdump", "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame_residual"]["cause"] == "reserved-unused-low-spill-region"
    assert payload["frame_residual"]["closability_tier"] == "ceiling"
    assert "lifetime-layout" not in payload["next_steps"][0]
    assert "lifetime-layout probes" not in payload["frame_residual"]["message"]
    assert "reserved-unused-low-spill-region" in payload["next_steps"][0]


def test_frame_residual_hint_from_report_includes_closability_fields() -> None:
    report = {
        "function": "fn_80000000",
        "summary": "fn_80000000: frame/local-area reservation differs",
        "current_low_frame_expansion": {
            "start": 24,
            "end": 28,
            "size": 4,
            "origin": "implicit-current-low-local-home",
            "current_accesses_in_range": [],
        },
        "frame_first_divergence": {
            "status": "diverged",
            "source_attribution": {
                "status": "source-object-attributed",
                "primary_source_object": {
                    "symbol": "local_temp",
                    "current_offset": 24,
                    "expected_offset": 28,
                },
            },
            "cause_hypothesis": {
                "kind": "lifetime-or-ordering-shift",
                "confidence": "medium",
                "source_object_symbol": "local_temp",
            },
            "verdict": {
                "status": "source-reachable-candidate",
                "source_object_symbol": "local_temp",
            },
        },
    }

    hint = debug_cli._frame_residual_hint_from_report(
        report,
        unit="melee/mn/sample",
    )

    assert hint is not None
    assert hint["kind"] == "frame-local-area"
    assert hint["cause"] == "lifetime-or-ordering-shift"
    assert hint["raw_cause"] == "lifetime-or-ordering-shift"
    assert hint["verdict"] == "source-reachable-candidate"
    assert hint["closability_tier"] == "gen-gated-366"
    assert hint["source_object_symbol"] == "local_temp"
    assert hint["next_steps"][0].startswith(
        "melee-agent debug mutate frame-transform-search -f fn_80000000"
    )


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
