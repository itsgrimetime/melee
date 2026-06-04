from __future__ import annotations

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app


runner = CliRunner()


BASELINE_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-80(r1)
        stfd f31,72(r1)
        stmw r27,44(r1)
        lmw r27,44(r1)
        lfd f31,72(r1)
        addi r1,r1,80
""")


BASELINE_LARGE_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-112(r1)
        stfd f31,104(r1)
        stmw r27,84(r1)
        lmw r27,84(r1)
        lfd f31,104(r1)
        addi r1,r1,112
""")


EXPECTED_ASM = textwrap.dedent("""\
    .fn fn_80000000, global
    /* 80000000 */    mflr r0
    /* 80000004 */    stw r0, 0x4(r1)
    /* 80000008 */    stwu r1, -0x60(r1)
    /* 8000000C */    stfd f31, 0x58(r1)
    /* 80000010 */    stmw r27, 0x44(r1)
    /* 80000014 */    lmw r27, 0x44(r1)
    /* 80000018 */    lfd f31, 0x58(r1)
    /* 8000001C */    addi r1, r1, 0x60
    .endfn fn_80000000
""")


FIXED_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-96(r1)
        stfd f31,88(r1)
        stmw r27,68(r1)
        lmw r27,68(r1)
        lfd f31,88(r1)
        addi r1,r1,96
""")


SOURCE_WITH_FRAME_LEVERS = textwrap.dedent("""\
    void fn_80000000(HSD_CObj* cobj, int arg1, int arg2)
    {
        f32 far_val;
        f32 bottom;

        far_val = 2.0f;
        bottom = (f32) arg2;
        setup();
        HSD_CObjSetFar(cobj, far_val);
        HSD_CObjSetOrtho(cobj, 0.0f, bottom, 0.0f, (f32) arg1);
    }
""")


def test_frame_transform_search_scores_text_candidates(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    unchanged = tmp_path / "unchanged.txt"
    fixed = tmp_path / "fixed.txt"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    unchanged.write_text(BASELINE_PCDUMP)
    fixed.write_text(FIXED_PCDUMP)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--candidate",
            f"unchanged:manual={unchanged}",
            "--candidate",
            f"fixed:manual={fixed}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    evaluation = payload["frame_transform_probe_evaluation"]
    assert evaluation["verdict"] == "source-reachable-frame-transform"
    assert evaluation["best_variant"]["label"] == "fixed"
    assert evaluation["best_variant"]["candidate_frame_size"] == 96
    assert evaluation["best_variant"]["current_frame_size"] == 80
    assert evaluation["best_variant"]["expected_frame_size"] == 96
    assert payload["stop_condition"]["kind"] == "validated-frame-transform"
    assert payload["variants"][0]["rank"] == 1
    assert payload["variants"][0]["label"] == "fixed"


def test_frame_transform_search_lists_directed_probes_without_compile(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_LARGE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text(SOURCE_WITH_FRAME_LEVERS)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    operators = {probe["operator"] for probe in payload["probes"]}
    assert "frame-direct-literal-at-final-fp-call" in operators
    assert "frame-split-fp-const-lifetime" in operators
    assert "frame-magic-scratch-relocation" in operators
    assert payload["probe_plan"]["status"] == "ready"
    assert payload["operator_filter"]
    assert payload["generated_source_dir"] is not None
    retained = [
        probe["source_retained"]
        for probe in payload["probes"]
        if probe["operator"] == "frame-direct-literal-at-final-fp-call"
    ]
    assert retained
    assert Path(retained[0]).exists()
    assert payload["variants"] == []
    assert payload["frame_transform_probe_evaluation"]["verdict"] == "no-probes"


def test_frame_transform_search_scores_source_candidate_with_match_percent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return FIXED_PCDUMP

    def fake_real_score(*args, **kwargs):
        return debug_cli._SourceCandidateRealScore(
            match_percent=99.75,
            match_percent_error=None,
            stack_slot_localizer=None,
            stack_slot_error=None,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fake_real_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--candidate",
            f"source:frame-direct-literal-at-final-fp-call={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "ok"
    assert variant["match_percent"] == 99.75
    assert variant["source_retained"] == str(source)
    assert variant["candidate_frame_size"] == 96


def test_frame_transform_search_rejects_wrong_function_text_candidate(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    wrong = tmp_path / "wrong.txt"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    wrong.write_text(
        BASELINE_PCDUMP.replace("fn_80000000", "fn_80000001")
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--candidate",
            f"wrong:manual={wrong}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "failed"
    assert "fn_80000000 not found in pcdump" in variant["error"]


def test_frame_transform_search_no_expected_preserves_candidate_evidence(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    fixed = tmp_path / "fixed.txt"
    baseline.write_text(BASELINE_PCDUMP)
    fixed.write_text(FIXED_PCDUMP)

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--no-expected",
            "--candidate",
            f"fixed:manual={fixed}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame_transform_probe_evaluation"]["verdict"] == "no-target"
    assert payload["variants"][0]["label"] == "fixed"
    assert payload["variants"][0]["candidate_frame_size"] == 96


def test_frame_transform_search_worsened_candidate_is_not_ceiling(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    worse = tmp_path / "worse.txt"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    worse.write_text(
        BASELINE_PCDUMP.replace("stwu r1,-80", "stwu r1,-64").replace(
            "addi r1,r1,80",
            "addi r1,r1,64",
        )
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--candidate",
            f"worse:manual={worse}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["frame_transform_probe_evaluation"]["verdict"] == (
        "frame-transform-results-inconclusive"
    )
    assert payload["stop_condition"]["status"] == "not-satisfied"


def test_frame_transform_search_records_source_compile_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from src.mwcc_debug.diff_capture import CompileFailure

    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        raise CompileFailure(
            side=diff_input.label,
            command=["debug", "dump", "local"],
            stdout="",
            stderr="compile failed",
            returncode=1,
        )

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--candidate",
            f"source:frame-direct-literal-at-final-fp-call={source}",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert variant["status"] == "failed"
    assert variant["source_retained"] == str(source)
    assert "compile failed" in variant["error"]
    assert payload["stop_condition"]["status"] == "not-satisfied"


def test_frame_transform_search_no_score_match_percent_skips_real_tree_score(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return FIXED_PCDUMP

    def fail_real_score(*args, **kwargs):
        raise AssertionError("real-tree scoring should not run")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_score_source_candidate_real_tree",
        fail_real_score,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "mutate",
            "frame-transform-search",
            "-f",
            "fn_80000000",
            "--pcdump",
            str(baseline),
            "--expected-asm",
            str(expected),
            "--candidate",
            f"source:frame-direct-literal-at-final-fp-call={source}",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "ok"
    assert "match_percent" not in variant
    assert variant["candidate_frame_size"] == 96
