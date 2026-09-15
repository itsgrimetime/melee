from __future__ import annotations

import json
import subprocess
import textwrap
from contextlib import nullcontext
from types import SimpleNamespace

from typer.testing import CliRunner

import src.cli.debug as debug_cli
import src.cli.debug.target as target_cli
import src.mwcc_debug as mwcc_debug_module
import src.mwcc_debug.diff_capture as diff_capture
from src.cli import app
from src.cli.debug import _probe_requires_full_unit_source
from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe


BASELINE_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x08 SPILLED
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 1 1 0x00
          interferers: 40=r26
        1 40 r26 1 1 0x00
          interferers: 37=r25
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-56(r1)
        stmw r25,24(r1)
        blr
""")

COALESCED_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        lwz r37,12(r32)
        add r40,r37,r33
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 37 1 1 0x00
        1 40 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 37 r25 0 0 0x00
          interferers:
        1 40 r25 0 0 0x00
          interferers:
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r26,24(r1)
        blr
""")


def test_probe_requires_full_unit_source_accepts_probe_and_serialized_forms() -> None:
    probe = LifetimeLayoutProbe(
        label="transform-corpus-unused-trailing-parameter-0",
        operator="transform-corpus:unused_trailing_parameter",
        description="remove trailing unused parameter",
        source_text="static int helper(int value) { return value; }\n",
        provenance={
            "kind": "transform-corpus",
            "requires_full_unit_source": True,
            "payload": {"requires_full_unit_source": True},
        },
    )

    assert _probe_requires_full_unit_source(probe) is True
    assert _probe_requires_full_unit_source(probe.to_dict()) is True


def test_probe_requires_full_unit_source_defaults_false_for_ordinary_probe() -> None:
    probe = LifetimeLayoutProbe(
        label="narrow-local",
        operator="narrow_local_lifetime",
        description="narrow local lifetime",
        source_text="void demo(void) {}\n",
        provenance={"kind": "lifetime-layout"},
    )

    assert _probe_requires_full_unit_source(probe) is False
    assert _probe_requires_full_unit_source(probe.to_dict()) is False


def test_real_tree_scoring_full_unit_writes_whole_candidate_and_restores(
    tmp_path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "repo"
    target = melee_root / "src" / "melee" / "demo.c"
    target.parent.mkdir(parents=True)
    original = (
        "static int fn_80000000(int value, int unused) { return value; }\n"
        "int caller(void) { return fn_80000000(1, 0); }\n"
    )
    candidate_text = (
        "static int fn_80000000(int value) { return value; }\n"
        "int caller(void) { return fn_80000000(1); }\n"
    )
    target.write_text(original)
    candidate = tmp_path / "candidate.c"
    candidate.write_text(candidate_text)

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_acquire_source_score_repo_lock",
        lambda root, timeout=None: nullcontext(),
    )

    def fail_transfer(*args, **kwargs):
        raise AssertionError("full-unit scoring must not transfer only the target")

    def fake_ninja(args, root, *, timeout=None):
        assert root == melee_root
        assert target.read_text() == candidate_text
        return subprocess.CompletedProcess(args, 0, "", ""), False

    def fake_refresh(unit, function, root, **kwargs):
        assert unit == "melee/demo"
        assert function == "fn_80000000"
        assert root == melee_root
        assert target.read_text() == candidate_text
        return 88.5, None

    monkeypatch.setattr(debug_cli, "transfer_candidate", fail_transfer)
    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(debug_cli, "_refresh_match_pct_after_successful_build", fake_refresh)
    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        lambda args, cwd, timeout=None: subprocess.CompletedProcess(args, 0, "", ""),
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    score = debug_cli._score_source_candidate_real_tree(
        candidate,
        function="fn_80000000",
        melee_root=melee_root,
        timeout=1,
        full_unit_source=True,
    )

    assert score.match_percent == 88.5
    assert score.match_percent_error is None
    assert target.read_text() == original


def test_real_tree_scoring_full_unit_structural_guard_rebuilds_checkdiff(
    tmp_path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "repo"
    target = melee_root / "src" / "melee" / "demo.c"
    target.parent.mkdir(parents=True)
    original = (
        "static int fn_80000000(int value, int unused) { return value; }\n"
        "int caller(void) { return fn_80000000(1, 0); }\n"
    )
    candidate_text = (
        "static int fn_80000000(int value) { return value; }\n"
        "int caller(void) { return fn_80000000(1); }\n"
    )
    target.write_text(original)
    candidate = tmp_path / "candidate.c"
    candidate.write_text(candidate_text)
    checkdiff_calls = []

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )
    monkeypatch.setattr(
        debug_cli,
        "_acquire_source_score_repo_lock",
        lambda root, timeout=None: nullcontext(),
    )
    monkeypatch.setattr(
        debug_cli,
        "transfer_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("full-unit scoring must not transfer only the target")
        ),
    )

    def fake_ninja(args, root, *, timeout=None):
        assert target.read_text() == candidate_text
        return subprocess.CompletedProcess(args, 0, "", ""), False

    def fake_refresh(unit, function, root, **kwargs):
        assert target.read_text() == candidate_text
        return 75.0, None

    def fake_checkdiff_json(
        function,
        *,
        melee_root,
        timeout=None,
        no_build=True,
        label,
        locked_child=False,
        disable_fingerprint=False,
    ):
        assert target.read_text() == candidate_text
        checkdiff_calls.append(
            {
                "no_build": no_build,
                "locked_child": locked_child,
                "disable_fingerprint": disable_fingerprint,
            }
        )
        return {
            "classification": {
                "primary": "instruction-sequence",
                "structural_truth_gate": {"normalized_diff_lines": 6},
                "stack_frame_sizes": {
                    "expected_frame_size": 48,
                    "current_frame_size": 48,
                },
            },
            "structural": {
                "normalized_diff_lines": 6,
                "opcode_similarity": 0.5,
                "line_delta": 2,
                "hunk_count": 1,
            },
        }, None

    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(debug_cli, "_refresh_match_pct_after_successful_build", fake_refresh)
    monkeypatch.setattr(debug_cli, "_run_checkdiff_json", fake_checkdiff_json)
    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        lambda args, cwd, timeout=None: subprocess.CompletedProcess(args, 0, "", ""),
    )

    score = debug_cli._score_source_candidate_real_tree(
        candidate,
        function="fn_80000000",
        melee_root=melee_root,
        timeout=1,
        include_structural_guard=True,
        full_unit_source=True,
    )

    assert checkdiff_calls == [
        {
            "no_build": False,
            "locked_child": True,
            "disable_fingerprint": True,
        }
    ]
    assert score.structural_guard["accepted"] is False
    assert score.structural_guard["classification_primary"] == "instruction-sequence"
    assert target.read_text() == original


def test_score_source_cli_forwards_full_unit_source_to_checkdiff_guard(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    wibo = tmp_path / "wibo"
    wibo.write_text("", encoding="utf-8")
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    (compiler_dir / "mwcceppc_debug.exe").write_text("", encoding="utf-8")
    captured_full_unit_flags = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_score_source_unsafe_lane_payload",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda unit: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_load_target_spec", lambda path: {})
    monkeypatch.setattr(
        debug_cli,
        "_score_source_target_details",
        lambda result, target_spec: {
            "matched": 0,
            "targeted": 0,
            "virtuals": {},
        },
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_expression_source",
        lambda path, *, melee_root: ("void fn_80000000(void) {}\n", str(path)),
    )
    monkeypatch.setattr(debug_cli, "_score_expression_anchors", lambda **kwargs: None)
    monkeypatch.setattr(
        target_cli,
        "_score_source_compile_source_rel",
        lambda **kwargs: nullcontext(kwargs["source_rel"]),
    )

    def fake_run_command(args, *, cwd, env, timeout=None):
        (cwd / env["MWCC_DEBUG_PCDUMP_PATH"]).write_text(
            "pcdump\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_real_tree(candidate_path, **kwargs):
        captured_full_unit_flags.append(kwargs.get("full_unit_source", False))
        return SimpleNamespace(
            structural_guard={"accepted": True},
            structural_guard_error=None,
            match_percent_error=None,
        )

    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        fake_run_command,
    )
    monkeypatch.setattr(debug_cli, "_score_source_candidate_real_tree", fake_real_tree)
    monkeypatch.setattr(
        mwcc_debug_module,
        "parse_pcdump",
        lambda text: [SimpleNamespace(name="fn_80000000")],
    )
    monkeypatch.setattr(mwcc_debug_module, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(
        mwcc_debug_module,
        "find_function",
        lambda events, function: None,
    )
    monkeypatch.setattr(
        mwcc_debug_module,
        "score_function",
        lambda fn, target_spec, events=None: SimpleNamespace(total=0),
    )

    base_args = [
        "debug",
        "target",
        "score-source",
        str(source),
        "--function",
        "fn_80000000",
        "--target",
        str(target),
        "--cflags-from",
        str(source),
        "--checkdiff-guard",
        "--json",
    ]
    result = runner.invoke(app, [*base_args, "--full-unit-source"])

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert captured_full_unit_flags[-1] is True
    assert payload["full_unit_source"] is True
    assert payload["function"] == "fn_80000000"
    assert payload["score_function"] == "fn_80000000"
    assert payload["source_file"] == "src/melee/demo.c"
    assert payload["source_retained"] == "src/melee/demo.c"
    assert payload["c_file"] == str(source)
    assert payload["cflags_from"] == "src/melee/demo.c"
    assert payload["candidate_id"] == "demo"

    result = runner.invoke(app, base_args)

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert captured_full_unit_flags[-1] is False
    assert payload["full_unit_source"] is False


def test_score_source_cli_auto_full_unit_guard_for_staged_generated_source(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    melee_root = tmp_path / "repo"
    unit_source = melee_root / "src" / "melee" / "demo.c"
    unit_source.parent.mkdir(parents=True)
    unit_source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    generated = melee_root / "build" / "demo" / "cases" / "candidate.c"
    generated.parent.mkdir(parents=True)
    generated.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    wibo = tmp_path / "wibo"
    wibo.write_text("", encoding="utf-8")
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    (compiler_dir / "mwcceppc_debug.exe").write_text("", encoding="utf-8")
    captured_full_unit_flags = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_score_source_unsafe_lane_payload",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda unit: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_load_target_spec", lambda path: {})
    monkeypatch.setattr(
        debug_cli,
        "_score_source_target_details",
        lambda result, target_spec: {
            "matched": 0,
            "targeted": 0,
            "virtuals": {},
        },
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_expression_source",
        lambda path, *, melee_root: ("void fn_80000000(void) {}\n", str(path)),
    )
    monkeypatch.setattr(debug_cli, "_score_expression_anchors", lambda **kwargs: None)
    monkeypatch.setattr(
        target_cli,
        "_score_source_compile_source_rel",
        lambda **kwargs: nullcontext(kwargs["source_rel"]),
    )

    def fake_run_command(args, *, cwd, env, timeout=None):
        (cwd / env["MWCC_DEBUG_PCDUMP_PATH"]).write_text(
            "pcdump\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_real_tree(candidate_path, **kwargs):
        captured_full_unit_flags.append(kwargs.get("full_unit_source", False))
        return SimpleNamespace(
            structural_guard={"accepted": True},
            structural_guard_error=None,
            match_percent_error=None,
        )

    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        fake_run_command,
    )
    monkeypatch.setattr(debug_cli, "_score_source_candidate_real_tree", fake_real_tree)
    monkeypatch.setattr(
        mwcc_debug_module,
        "parse_pcdump",
        lambda text: [SimpleNamespace(name="fn_80000000")],
    )
    monkeypatch.setattr(mwcc_debug_module, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(
        mwcc_debug_module,
        "find_function",
        lambda events, function: None,
    )
    monkeypatch.setattr(
        mwcc_debug_module,
        "score_function",
        lambda fn, target_spec, events=None: SimpleNamespace(total=0),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "score-source",
            str(generated),
            "--function",
            "fn_80000000",
            "--target",
            str(target),
            "--cflags-from",
            str(unit_source),
            "--checkdiff-guard",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert captured_full_unit_flags == [True]
    assert payload["full_unit_source"] is True


def test_score_source_cli_rejects_structural_guard_when_target_score_misses_all(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text('{"function":"fn_80000000","virtuals":{"33":28,"39":26}}\n')
    wibo = tmp_path / "wibo"
    wibo.write_text("", encoding="utf-8")
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    (compiler_dir / "mwcceppc_debug.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_score_source_unsafe_lane_payload",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda unit: ("", "mwcc"))
    monkeypatch.setattr(debug_cli, "_load_target_spec", lambda path: {})
    monkeypatch.setattr(
        debug_cli,
        "_score_source_target_details",
        lambda result, target_spec: {
            "matched": 0,
            "targeted": 2,
            "virtuals": {
                "33": {"expected": 28, "actual": 26, "matched": False},
                "39": {"expected": 26, "actual": 28, "matched": False},
            },
        },
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_expression_source",
        lambda path, *, melee_root: ("void fn_80000000(void) {}\n", str(path)),
    )
    monkeypatch.setattr(debug_cli, "_score_expression_anchors", lambda **kwargs: None)
    monkeypatch.setattr(
        target_cli,
        "_score_source_compile_source_rel",
        lambda **kwargs: nullcontext(kwargs["source_rel"]),
    )

    def fake_run_command(args, *, cwd, env, timeout=None):
        (cwd / env["MWCC_DEBUG_PCDUMP_PATH"]).write_text(
            "pcdump\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_real_tree(candidate_path, **kwargs):
        return SimpleNamespace(
            structural_guard={
                "accepted": True,
                "shape_preserved": True,
                "classification_primary": "normalized-structural-match",
                "normalized_diff_lines": 0,
                "hunk_count": 7,
                "rejection_reason": None,
            },
            structural_guard_error=None,
            match_percent_error=None,
        )

    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        fake_run_command,
    )
    monkeypatch.setattr(debug_cli, "_score_source_candidate_real_tree", fake_real_tree)
    monkeypatch.setattr(
        mwcc_debug_module,
        "parse_pcdump",
        lambda text: [SimpleNamespace(name="fn_80000000")],
    )
    monkeypatch.setattr(mwcc_debug_module, "parse_hook_events", lambda text: [])
    monkeypatch.setattr(
        mwcc_debug_module,
        "find_function",
        lambda events, function: None,
    )
    monkeypatch.setattr(
        mwcc_debug_module,
        "score_function",
        lambda fn, target_spec, events=None: SimpleNamespace(total=140),
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "score-source",
            str(source),
            "--function",
            "fn_80000000",
            "--target",
            str(target),
            "--cflags-from",
            str(source),
            "--checkdiff-guard",
            "--full-unit-source",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["target_score"]["matched"] == 0
    assert payload["target_score"]["targeted"] == 2
    assert payload["structural_guard"]["shape_preserved"] is True
    assert payload["structural_guard"]["accepted"] is False
    assert payload["structural_guard"]["target_score_accepted"] is False
    assert payload["structural_guard"]["target_score_matched"] == 0
    assert payload["structural_guard"]["target_score_targeted"] == 2
    assert payload["candidate_verdict"] == {
        "classification": "target-score-miss",
        "ledger": "revert candidate",
        "matched": 0,
        "targeted": 2,
        "reason": "target score missed all requested registers",
    }


def test_score_source_force_phys_mode_applies_checkdiff_guard(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    target = tmp_path / "target.yaml"
    target.write_text("force_phys: {37: 25}\n", encoding="utf-8")
    wibo = tmp_path / "wibo"
    wibo.write_text("", encoding="utf-8")
    compiler_dir = tmp_path / "compiler"
    compiler_dir.mkdir()
    (compiler_dir / "mwcceppc_debug.exe").write_text("", encoding="utf-8")
    captured_full_unit_flags = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_score_source_unsafe_lane_payload",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(debug_cli, "_find_wibo", lambda: wibo)
    monkeypatch.setattr(debug_cli, "_find_compiler_dir", lambda: compiler_dir)
    monkeypatch.setattr(debug_cli, "_ninja_cflags_for_unit", lambda unit: ("", "mwcc"))
    monkeypatch.setattr(
        debug_cli,
        "_read_expression_source",
        lambda path, *, melee_root: ("void fn_80000000(void) {}\n", str(path)),
    )
    monkeypatch.setattr(
        target_cli,
        "_score_source_compile_source_rel",
        lambda **kwargs: nullcontext(kwargs["source_rel"]),
    )

    def fake_run_command(args, *, cwd, env, timeout=None):
        (cwd / env["MWCC_DEBUG_PCDUMP_PATH"]).write_text(
            "pcdump\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_real_tree(candidate_path, **kwargs):
        captured_full_unit_flags.append(kwargs.get("full_unit_source", False))
        return SimpleNamespace(
            match_percent=87.5,
            structural_guard={
                "accepted": False,
                "classification_primary": "asm-diff",
                "normalized_diff_lines": 4,
                "hunk_count": 2,
            },
            structural_guard_error=None,
            match_percent_error=None,
        )

    monkeypatch.setattr(
        debug_cli,
        "_run_command_with_optional_timeout",
        fake_run_command,
    )
    monkeypatch.setattr(debug_cli, "_score_source_candidate_real_tree", fake_real_tree)
    monkeypatch.setattr(
        target_cli,
        "_score_source_force_phys_payload",
        lambda *args, **kwargs: {
            "score": 11,
            "target_score": {"matched": 1, "targeted": 2},
            "force_phys_score": {"matched": 1, "targeted": 2},
            "score_mode": "force-phys",
        },
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "score-source",
            str(source),
            "--function",
            "fn_80000000",
            "--target",
            str(target),
            "--cflags-from",
            str(source),
            "--checkdiff-guard",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert captured_full_unit_flags == [False]
    assert payload["score_mode"] == "force-phys"
    assert payload["match_percent"] == 87.5
    assert payload["checkdiff_match_percent"] == 87.5
    assert payload["structural_guard"]["classification_primary"] == "asm-diff"
    assert payload["checkdiff_guard"] == {
        "match_percent": 87.5,
        "classification_primary": "asm-diff",
        "normalized_diff_lines": 4,
        "hunk_count": 2,
        "accepted": False,
    }


def test_score_source_cli_scopes_json_failure_payload(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_score_source_unsafe_lane_payload",
        lambda **kwargs: {"message": "blocked for test"},
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "target",
            "score-source",
            str(source),
            "--function",
            "fn_80000000",
            "--target",
            str(target),
            "--cflags-from",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"] == "unsafe local pcdump lane"
    assert payload["function"] == "fn_80000000"
    assert payload["score_function"] == "fn_80000000"
    assert payload["source_file"] == "src/melee/demo.c"
    assert payload["source_retained"] == "src/melee/demo.c"
    assert payload["c_file"] == str(source)
    assert payload["cflags_from"] == "src/melee/demo.c"
    assert payload["candidate_id"] == "demo"


def test_coalesce_search_transform_probe_passes_unit_source_for_full_unit(
    tmp_path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    melee_root = tmp_path / "repo"
    source = melee_root / "src" / "melee" / "demo.c"
    source.parent.mkdir(parents=True)
    source.write_text(
        "static int fn_80000000(int value, int unused) {\n"
        "    return value;\n"
        "}\n"
        "int caller(void) { return fn_80000000(1, 0); }\n"
    )
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE_PCDUMP)
    compile_unit_sources = []
    match_full_unit_flags = []

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/demo",
    )

    def fake_compile(*args, **kwargs):
        compile_unit_sources.append(kwargs.get("unit_source"))
        return COALESCED_PCDUMP

    def fake_match_percent(*args, **kwargs):
        match_full_unit_flags.append(kwargs.get("full_unit_source", False))
        return 99.0, None

    monkeypatch.setattr(diff_capture, "compile_source_variant", fake_compile)
    monkeypatch.setattr(debug_cli, "_select_order_source_match_percent", fake_match_percent)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--include-transform-corpus",
            "--transform-family",
            "unused_trailing_parameter",
            "--transform-force-phys",
            "1:3",
            "--compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert any(
        probe.get("mutator_key") == "remove_unused_trailing_parameter"
        for probe in payload["probes"]
    )
    assert source in compile_unit_sources
    assert True in match_full_unit_flags
