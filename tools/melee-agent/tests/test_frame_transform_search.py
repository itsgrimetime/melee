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


FIXED_88_PCDUMP = textwrap.dedent("""\
    Starting function fn_80000000
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mflr r0
        stw r0,4(r1)
        stwu r1,-88(r1)
        stfd f31,80(r1)
        stmw r27,60(r1)
        lmw r27,60(r1)
        lfd f31,80(r1)
        addi r1,r1,88
""")


EXPECTED_88_ASM = textwrap.dedent("""\
    .fn fn_80000000, global
    /* 80000000 */    mflr r0
    /* 80000004 */    stw r0, 0x4(r1)
    /* 80000008 */    stwu r1, -0x58(r1)
    /* 8000000C */    stfd f31, 0x50(r1)
    /* 80000010 */    stmw r27, 0x3c(r1)
    /* 80000014 */    lmw r27, 0x3c(r1)
    /* 80000018 */    lfd f31, 0x50(r1)
    /* 8000001C */    addi r1, r1, 0x58
    .endfn fn_80000000
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


SOURCE_SIMPLE_FRAME = textwrap.dedent("""\
    void fn_80000000(int arg)
    {
        int count;
        sink(arg + count);
    }
""")


SOURCE_C89_ARRAY_DECLS = textwrap.dedent("""\
    void fn_80000000(int arg)
    {
        CardState* state = arg0;
        CardBufEntry* entry;
        s32 block_map[64];
        s32 blocks_before;
        u8* dst;

        blocks_before = arg;
        sink(dst);
    }
""")


SOURCE_WITH_SEMANTIC_FRAME_LEVER = textwrap.dedent("""\
    void fn_80000000(int x)
    {
        int tmp = x + 1;
        sink(tmp);
    }
""")

TRANSFORM_ASSIGNMENT_SOURCE = textwrap.dedent("""\
    void fn_80000000(void)
    {
        int x;
        x = 1;
        sink(x);
    }
""")


def _assert_comma_transform_probe(probe: dict) -> None:
    assert probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
    assert probe["provenance"]["kind"] == "transform-corpus"
    assert probe["family_id"] == "comma_operator_noop_expression_shape"
    assert probe["mutator_key"] == "wrap_comma_noop_assignment_rhs"
    assert probe["probe_id"] == "comma_operator_noop_expression_shape@0"


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
    assert payload["semantic_lever_status"]["status"] == "no-safe-semantic-lever"
    assert payload["frame_transform_probe_evaluation"]["verdict"] == (
        "no-safe-semantic-lever"
    )


def test_frame_transform_search_opt_in_lists_transform_corpus_probe_json(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE_PCDUMP)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

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
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--include-transform-corpus",
            "--transform-family",
            "comma_operator_noop_expression_shape",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
    )
    _assert_comma_transform_probe(probe)
    assert "frame-direct-literal-at-final-fp-call" in payload["operator_filter"]
    assert probe["operator"] not in payload["operator_filter"]


def test_frame_transform_search_transform_family_overrides_default_corpus_families(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE_PCDUMP)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

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
            "--source-file",
            str(source),
            "--no-compile-probes",
            "--transform-family",
            "comma_operator_noop_expression_shape",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    transform_operators = [
        probe["operator"]
        for probe in payload["probes"]
        if probe["operator"].startswith("transform-corpus:")
    ]
    assert transform_operators == [
        "transform-corpus:comma_operator_noop_expression_shape"
    ]


def test_frame_transform_search_max_probes_keeps_directed_probe_before_corpus(
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
            "--include-transform-corpus",
            "--transform-family",
            "comma_operator_noop_expression_shape",
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["probes"]) == 1
    assert not payload["probes"][0]["operator"].startswith("transform-corpus:")


def test_frame_transform_search_lists_semantic_dematerialize_probe_without_compile(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_LARGE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text(SOURCE_WITH_SEMANTIC_FRAME_LEVER)

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
            "--max-probes",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "frame-local-dematerialize"
    )
    assert payload["semantic_lever_status"]["status"] == "semantic-lever-generated"
    assert probe["provenance"]["local"] == "tmp"
    assert "sink(((int) (x + 1)));" in Path(probe["source_retained"]).read_text()


def test_frame_transform_search_reports_no_safe_semantic_lever_without_ceiling(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_LARGE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text(textwrap.dedent("""\
        void fn_80000000(int x)
        {
            int tmp = helper(x);
            sink(tmp);
        }
    """))

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
    assert payload["semantic_lever_status"]["status"] == "no-safe-semantic-lever"
    evaluation = payload["frame_transform_probe_evaluation"]
    assert evaluation["verdict"] == "no-safe-semantic-lever"
    assert payload["stop_condition"]["kind"] == "no-safe-semantic-lever"


def test_frame_transform_search_lists_forced_pad_stack_probe_for_frame_delta(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_88_ASM)
    source.write_text(SOURCE_SIMPLE_FRAME)

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
            "--operator",
            "frame-reservation-pad-stack",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probes = [
        probe for probe in payload["probes"]
        if probe["operator"] == "frame-reservation-pad-stack"
    ]
    assert len(probes) == 1
    assert probes[0]["provenance"] == {
        "kind": "frame-reservation-pad-stack",
        "bytes": 8,
        "action": "insert",
        "delta": 8,
    }
    retained = Path(probes[0]["source_retained"])
    assert retained.exists()
    assert "PAD_STACK(8);" in retained.read_text()


def test_frame_transform_search_accepts_explicit_frame_reservation_bytes(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_PCDUMP)
    source.write_text(SOURCE_SIMPLE_FRAME)

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
            "--source-file",
            str(source),
            "--operator",
            "frame-reservation-pad-stack",
            "--frame-reservation-bytes",
            "8",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "frame-reservation-pad-stack"
    )
    assert probe["provenance"]["bytes"] == 8
    assert "PAD_STACK(8);" in Path(probe["source_retained"]).read_text()


def test_frame_transform_search_inserts_pad_stack_after_c89_array_decls(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_PCDUMP)
    source.write_text(SOURCE_C89_ARRAY_DECLS)

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
            "--source-file",
            str(source),
            "--operator",
            "frame-reservation-pad-stack",
            "--frame-reservation-bytes",
            "8",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    probe = next(
        probe for probe in payload["probes"]
        if probe["operator"] == "frame-reservation-pad-stack"
    )
    retained = Path(probe["source_retained"]).read_text()
    assert retained.index("u8* dst;") < retained.index("PAD_STACK(8);")
    assert retained.index("PAD_STACK(8);") < retained.index("blocks_before = arg;")


def test_frame_transform_search_compiles_forced_pad_stack_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_PCDUMP)
    expected.write_text(EXPECTED_88_ASM)
    source.write_text(SOURCE_SIMPLE_FRAME)

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        if diff_input.label == "source-baseline":
            return BASELINE_PCDUMP
        assert Path(diff_input.path).read_text().count("PAD_STACK(8);") == 1
        return FIXED_88_PCDUMP

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
            "--source-file",
            str(source),
            "--operator",
            "frame-reservation-pad-stack",
            "--compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert variant["status"] == "ok"
    assert variant["operator"] == "frame-reservation-pad-stack"
    assert variant["candidate_frame_size"] == 88
    assert variant["probe"]["provenance"]["delta"] == 8
    assert payload["frame_transform_probe_evaluation"]["verdict"] == (
        "diagnostic-pad-stack-frame-transform"
    )
    assert payload["stop_condition"]["kind"] == "diagnostic-pad-stack-only"


def test_frame_transform_search_compiles_semantic_dematerialize_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    source = tmp_path / "source.c"
    baseline.write_text(BASELINE_LARGE_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    source.write_text(SOURCE_WITH_SEMANTIC_FRAME_LEVER)

    def fake_compile(diff_input, *, function, melee_root, timeout) -> str:
        if diff_input.label == "source-baseline":
            return BASELINE_LARGE_PCDUMP
        probe_source = Path(diff_input.path).read_text()
        assert "int tmp = x + 1;" not in probe_source
        assert "sink(((int) (x + 1)));" in probe_source
        return FIXED_PCDUMP

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
            "--source-file",
            str(source),
            "--operator",
            "frame-local-dematerialize",
            "--compile-probes",
            "--no-score-match-percent",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    variant = payload["variants"][0]
    assert payload["semantic_lever_status"]["status"] == "semantic-lever-generated"
    assert variant["status"] == "ok"
    assert variant["operator"] == "frame-local-dematerialize"
    assert variant["candidate_frame_size"] == 96
    assert variant["probe"]["provenance"]["local"] == "tmp"
    assert payload["frame_transform_probe_evaluation"]["verdict"] == (
        "source-reachable-frame-transform"
    )


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


def test_frame_transform_search_bases_stop_condition_on_staged_source_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    staged_source = tmp_path / "staged.c"
    unchanged = tmp_path / "unchanged.txt"
    baseline.write_text(FIXED_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    staged_source.write_text("void fn_80000000(void) {}\n")
    unchanged.write_text(BASELINE_LARGE_PCDUMP)
    compile_calls = []

    def fake_compile(diff_input, **kwargs) -> str:
        compile_calls.append((diff_input.label, kwargs))
        return BASELINE_LARGE_PCDUMP

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
            "--source-file",
            str(staged_source),
            "--prefer-staged-source-baseline",
            "--candidate",
            f"unchanged:frame-direct-literal-at-final-fp-call={unchanged}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert compile_calls
    assert payload["frame_report"]["current"]["frame_size"] == 112
    assert payload["frame_transform_probe_evaluation"][
        "baseline_remaining_frame_delta"
    ] == -16
    assert payload["frame_report"]["staged_source_baseline"]["authoritative"] is True
    assert payload["frame_report"]["baseline_consistency"]["status"] == (
        "mismatch-staged-source-authoritative"
    )
    assert payload["variants"][0]["remaining_frame_delta"] == -16
    assert payload["stop_condition"]["kind"] == "bounded-frame-transform-ceiling"
    assert payload["stop_condition"]["baseline_remaining_frame_delta"] == -16


def test_frame_transform_search_resolves_symbolic_homes_from_staged_source_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    staged_source = tmp_path / "staged.c"
    unchanged = tmp_path / "unchanged.txt"
    symbolic_pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-112(r1)
            addi    r4,r1,totals
            stw     r3,0(r4); fIsPtrOp
            stb     r3,sorted_names_probe_3(r1)
            addi    r1,r1,112; fSideEffects
    """)
    staged_current_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */ stwu r1, -0x70(r1)
        /* 80000004 */ addi r4, r1, 0x20
        /* 80000008 */ stw r3, 0(r4)
        /* 8000000c */ stb r3, 0x40(r1)
        /* 80000010 */ addi r1, r1, 0x70
        .endfn fn_80000000
    """)
    baseline.write_text(FIXED_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    staged_source.write_text("void fn_80000000(void) {}\n")
    unchanged.write_text(symbolic_pcdump)
    current_asm_calls = []

    def fake_compile(diff_input, **kwargs) -> str:
        return symbolic_pcdump

    def fake_staged_current_asm(path, **kwargs) -> str:
        current_asm_calls.append((path, kwargs))
        return staged_current_asm

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_source_current_asm",
        fake_staged_current_asm,
        raising=False,
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
            "--source-file",
            str(staged_source),
            "--prefer-staged-source-baseline",
            "--candidate",
            f"unchanged:frame-direct-literal-at-final-fp-call={unchanged}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert current_asm_calls
    symbolic_homes = sorted(
        payload["frame_report"]["current"]["symbolic_home_map"],
        key=lambda item: item["symbol"],
    )
    assert symbolic_homes == [
        {"symbol": "sorted_names_probe_3", "offset": 64},
        {"symbol": "totals", "offset": 32},
    ]
    assert payload["frame_report"]["current"]["unresolved_symbolic_homes"] == []


def test_frame_transform_search_does_not_fallback_to_repo_current_for_staged_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    staged_source = tmp_path / "staged.c"
    unchanged = tmp_path / "unchanged.txt"
    symbolic_pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-112(r1)
            addi    r4,r1,totals
            stw     r3,0(r4); fIsPtrOp
            addi    r1,r1,112; fSideEffects
    """)
    baseline.write_text(FIXED_PCDUMP)
    expected.write_text(EXPECTED_ASM)
    staged_source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)
    unchanged.write_text(symbolic_pcdump)

    def fake_compile(diff_input, **kwargs) -> str:
        return symbolic_pcdump

    def fake_staged_current_asm(path, **kwargs):
        return None

    def fail_repo_current_asm(*args, **kwargs):
        raise AssertionError("must not read repo current asm for staged baseline")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_source_current_asm",
        fake_staged_current_asm,
        raising=False,
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_current_asm",
        fail_repo_current_asm,
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
            "--source-file",
            str(staged_source),
            "--include-transform-corpus",
            "--transform-family",
            "comma_operator_noop_expression_shape",
            "--candidate",
            f"unchanged:frame-direct-literal-at-final-fp-call={unchanged}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert any(
        probe["operator"] == "transform-corpus:comma_operator_noop_expression_shape"
        for probe in payload["probes"]
    )
    assert payload["frame_report"]["current"]["frame_size"] == 96
    assert payload["frame_report"]["staged_source_baseline"] == {
        "status": "compiled",
        "source": str(staged_source),
        "current_asm_status": "pcdump-only",
        "authoritative": False,
    }
    assert payload["frame_report"]["baseline_consistency"]["status"] == (
        "mismatch-explicit-pcdump-authoritative"
    )
    consistency = payload["frame_report"]["baseline_consistency"]
    assert consistency["pcdump_current_frame_size"] == 96
    assert consistency["staged_current_frame_size"] == 112
    assert payload["variants"][0]["current_frame_size"] == 96


def test_frame_transform_search_resolves_explicit_pcdump_homes_from_retained_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    expected = tmp_path / "expected.s"
    staged_source = tmp_path / "staged.c"
    unchanged = tmp_path / "unchanged.txt"
    symbolic_pcdump = textwrap.dedent("""\
        Starting function fn_80000000
        FINAL CODE AFTER INSTRUCTION SCHEDULING
        fn_80000000
        B0: Succ={} Pred={} Labels={}
            stwu    r1,-176(r1)
            stw     r3,@1540(r1)
            stw     r4,@1540+4(r1)
            stw     r5,@1539(r1)
            stw     r6,@1539+4(r1)
            stmw    r26,88(r1)
            stfd    f31,168(r1)
            addi    r1,r1,176; fSideEffects
    """)
    expected_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */ stwu r1, -0xa8(r1)
        /* 80000004 */ stw r3, 0x40(r1)
        /* 80000008 */ stw r4, 0x44(r1)
        /* 8000000c */ stw r5, 0x48(r1)
        /* 80000010 */ stw r6, 0x4c(r1)
        /* 80000014 */ stmw r26, 0x50(r1)
        /* 80000018 */ stfd f31, 0xa0(r1)
        /* 8000001c */ addi r1, r1, 0xa8
        .endfn fn_80000000
    """)
    retained_current_asm = textwrap.dedent("""\
        .fn fn_80000000, global
        /* 80000000 */ stwu r1, -0xb0(r1)
        /* 80000004 */ stw r3, 0x40(r1)
        /* 80000008 */ stw r4, 0x44(r1)
        /* 8000000c */ stw r5, 0x48(r1)
        /* 80000010 */ stw r6, 0x4c(r1)
        /* 80000014 */ stmw r26, 0x58(r1)
        /* 80000018 */ stfd f31, 0xa8(r1)
        /* 8000001c */ addi r1, r1, 0xb0
        .endfn fn_80000000
    """)
    baseline.write_text(symbolic_pcdump)
    expected.write_text(expected_asm)
    staged_source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)
    unchanged.write_text(symbolic_pcdump)

    def fake_compile(diff_input, **kwargs) -> str:
        return symbolic_pcdump

    def fake_staged_current_asm(path, **kwargs) -> str:
        return retained_current_asm

    def fail_repo_current_asm(*args, **kwargs):
        raise AssertionError("must resolve explicit pcdump from retained source")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_source_current_asm",
        fake_staged_current_asm,
        raising=False,
    )
    monkeypatch.setattr(
        debug_cli,
        "_read_frame_reservation_current_asm",
        fail_repo_current_asm,
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
            "--source-file",
            str(staged_source),
            "--candidate",
            f"unchanged:frame-direct-literal-at-final-fp-call={unchanged}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    symbolic_homes = sorted(
        payload["frame_report"]["current"]["symbolic_home_map"],
        key=lambda item: item["symbol"],
    )
    assert symbolic_homes == [
        {"symbol": "@1539", "offset": 72},
        {"symbol": "@1539+4", "offset": 76},
        {"symbol": "@1540", "offset": 64},
        {"symbol": "@1540+4", "offset": 68},
    ]
    assert payload["frame_report"]["current"]["unresolved_symbolic_homes"] == []
    assert {"start": 80, "end": 88, "size": 8} in (
        payload["frame_report"]["current"]["unused_ranges"]
    )
    summary = payload["terminal_summary"]
    assert summary["blocker"] == "low-frame-gap-unattributed"
    assert summary["low_frame_gap"]["status"] == "remaining"
    assert summary["low_frame_gap"]["attribution_status"] == "unattributed"
    assert summary["low_frame_gap"]["start"] == 80
    assert summary["low_frame_gap"]["end"] == 88
    assert summary["low_frame_gap"]["size"] == 8
    assert payload["frame_report"]["staged_source_baseline"]["authoritative"] is False


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


def test_frame_transform_search_help_shows_transform_corpus_flags() -> None:
    result = runner.invoke(
        app,
        ["debug", "mutate", "frame-transform-search", "--help"],
        env={"COLUMNS": "160"},
    )

    assert result.exit_code == 0
    assert "--include-transform-corpus" in result.stdout
    assert "--transform-family" in result.stdout
    assert "--transform-force-phys" in result.stdout
    assert "--directed-force-phys" in result.stdout
