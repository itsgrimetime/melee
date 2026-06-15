from __future__ import annotations

import json
import subprocess
import textwrap
from contextlib import nullcontext

from typer.testing import CliRunner

import src.cli.debug as debug_cli
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
        lambda root: nullcontext(),
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
