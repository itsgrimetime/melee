"""Tests for coalesce-directed source-shape search ranking."""

from __future__ import annotations

import json
import pathlib
import textwrap
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug import cache as pcdump_cache
from src.mwcc_debug.coalesce_search import (
    rank_coalesce_candidates,
    score_coalesce_delta,
)
from src.mwcc_debug.pressure_explorer import (
    compare_pressure_signatures,
    pressure_signature_from_pcdump,
)

runner = CliRunner()


BASELINE = textwrap.dedent("""\
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


COALESCED = textwrap.dedent("""\
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


def _delta(candidate: str):
    baseline_sig = pressure_signature_from_pcdump(
        BASELINE,
        "fn_80000000",
        pairs=[(37, 40)],
    )
    candidate_sig = pressure_signature_from_pcdump(
        candidate,
        "fn_80000000",
        pairs=[(37, 40)],
    )
    return compare_pressure_signatures(baseline_sig, candidate_sig)


def test_coalesce_score_prioritizes_target_relationship_before_match_percent() -> None:
    coalesced = score_coalesce_delta(
        _delta(COALESCED),
        target_pairs=[(37, 40)],
        match_percent=12.0,
    )
    unchanged = score_coalesce_delta(
        _delta(BASELINE),
        target_pairs=[(37, 40)],
        match_percent=99.0,
    )

    ranked = rank_coalesce_candidates([
        {
            "label": "high-match-wrong-reason",
            "status": "ok",
            "objective": unchanged.to_dict(),
        },
        {
            "label": "coalesce-right-pair",
            "status": "ok",
            "objective": coalesced.to_dict(),
        },
    ])

    assert ranked[0]["label"] == "coalesce-right-pair"
    assert ranked[0]["objective"]["target_coalesced"] is True
    assert ranked[0]["objective"]["interference_removed"] is True


def test_coalesce_search_cli_ranks_candidate_pcdumps_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    coalesced = tmp_path / "coalesced.txt"
    baseline.write_text(BASELINE)
    unchanged.write_text(BASELINE)
    coalesced.write_text(COALESCED)

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
            "--candidate",
            f"high-match-wrong-reason:noop={unchanged}",
            "--candidate",
            f"coalesce-right-pair:temp-introduction={coalesced}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["target_pairs"] == [[37, 40]]
    assert payload["ranking"] == "target coalesce objective, final match percent tiebreaker"
    assert payload["variants"][0]["label"] == "coalesce-right-pair"
    assert payload["variants"][0]["objective"]["target_spill_removed"] == [37]
    assert payload["variants"][1]["label"] == "high-match-wrong-reason"


def test_coalesce_search_requires_fresh_cached_pcdump_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(pcdump, function, melee_root=None, *, require_fresh=False):
        assert require_fresh is True
        raise typer.Exit(4)

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fake_resolve)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 4


def test_coalesce_search_missing_function_in_pcdump_exits_cleanly(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE.replace("fn_80000000", "other_fn"))

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
        ],
    )

    assert result.exit_code == 3
    assert "function 'fn_80000000' not found in pcdump" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_coalesce_search_allow_stale_pcdump_opt_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    coalesced = tmp_path / "coalesced.txt"
    baseline.write_text(BASELINE)
    coalesced.write_text(COALESCED)

    def fake_resolve(pcdump, function, melee_root=None, *, require_fresh=False):
        assert require_fresh is False
        return baseline

    monkeypatch.setattr(debug_cli, "_resolve_pcdump_path", fake_resolve)

    result = runner.invoke(
        app,
        [
            "debug",
            "coalesce-search",
            "-f",
            "fn_80000000",
            "--target",
            "r37=r40",
            "--allow-stale-pcdump",
            "--candidate",
            f"coalesce-right-pair:temp-introduction={coalesced}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr


def test_coalesce_search_scores_source_candidate_match_percent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) {}\n")

    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: COALESCED,
    )
    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_match_percent",
        lambda *args, **kwargs: (88.25, None),
    )

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
            "--candidate",
            f"source-score:temp-introduction={candidate}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["variants"][0]["objective"]["match_percent"] == 88.25


def test_coalesce_search_split_var_generates_anti_coalesce_probes_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(BASELINE)
    source = tmp_path / "demo.c"
    source.write_text(textwrap.dedent("""\
        void fn_80000000(HSD_JObj* jobj)
        {
            Prep(jobj);
            HSD_JObjSetTranslateX(jobj, 1.0f);
            HSD_JObjSetMtxDirtySub(jobj);
        }
    """))

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
            "--split-var",
            "jobj",
            "--max-probes",
            "2",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    anti = [
        probe for probe in payload["probes"]
        if probe["operator"] == "anti-coalesce-volatile-copy"
    ]
    assert anti
    assert anti[0]["provenance"]["var"] == "jobj"


def test_coalesce_search_opt_in_lists_transform_corpus_probe_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

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


def test_coalesce_search_default_excludes_transform_corpus_probe_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "demo.c"
    baseline.write_text(BASELINE)
    source.write_text(TRANSFORM_ASSIGNMENT_SOURCE)

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
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert not any(
        probe["operator"].startswith("transform-corpus:")
        for probe in payload["probes"]
    )


def test_coalesce_search_non_json_emits_real_score_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    import src.mwcc_debug.diff_capture as diff_capture

    baseline = tmp_path / "baseline.txt"
    candidate = tmp_path / "candidate.c"
    baseline.write_text(BASELINE)
    candidate.write_text("void fn_80000000(void) {}\n")

    monkeypatch.setattr(
        diff_capture,
        "compile_source_variant",
        lambda *args, **kwargs: COALESCED,
    )

    def fake_match_percent(*args, status=None, **kwargs):
        assert status is not None
        status("build complete; refreshing report.json")
        return 88.25, None

    monkeypatch.setattr(
        debug_cli,
        "_select_order_source_match_percent",
        fake_match_percent,
    )

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
            "--candidate",
            f"source-score:temp-introduction={candidate}",
            "--no-compile-probes",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (
        "[coalesce-search] source-score: build complete; refreshing report.json"
        in result.stderr
    )


def test_real_tree_source_score_restores_source_and_preserves_legacy_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    melee_root = tmp_path
    unit = "melee/mn/demo"
    source_path = melee_root / "src" / f"{unit}.c"
    source_path.parent.mkdir(parents=True)
    original = textwrap.dedent("""\
        int untouched(void) { return 7; }

        void fn_80000000(void) {
            int digit_count = 0;
            (void) digit_count;
        }
    """)
    source_path.write_text(original)
    report_path = melee_root / "build" / "GALE01" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "units": [
            {
                "name": unit,
                "functions": [{"name": "fn_80000000"}],
            }
        ],
    }))

    cache_path = pcdump_cache.cache_path(melee_root, unit)
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(BASELINE)
    assert pcdump_cache.lookup(melee_root, unit).fresh is True
    assert not pcdump_cache.hash_path(cache_path).exists()

    candidate = tmp_path / "candidate.c"
    candidate.write_text(textwrap.dedent("""\
        void fn_80000000(void) {
            int digit_count = 0;
            digit_count += 1;
            (void) digit_count;
        }
    """))

    monkeypatch.setattr(
        debug_cli,
        "_run_ninja_with_no_diag_retry",
        lambda *args, **kwargs: (
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            False,
        ),
    )

    def stale_refresh(*args, **kwargs):
        raise typer.Exit(4)

    monkeypatch.setattr(
        debug_cli,
        "_refresh_match_pct_after_successful_build",
        stale_refresh,
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(typer.Exit) as excinfo:
        debug_cli._score_source_candidate_real_tree(
            candidate,
            function="fn_80000000",
            melee_root=melee_root,
            timeout=1.0,
        )

    assert excinfo.value.exit_code == 4
    assert source_path.read_text() == original
    entry = pcdump_cache.lookup(melee_root, unit)
    assert entry is not None
    assert entry.fresh is True
    assert pcdump_cache.hash_path(cache_path).exists()


def test_coalesce_search_help_smoke() -> None:
    result = runner.invoke(
        app,
        ["debug", "coalesce-search", "--help"],
        env={"COLUMNS": "160"},
    )

    assert result.exit_code == 0
    assert "--target" in result.stdout
    assert "--include-transform-corpus" in result.stdout
    assert "--transform-family" in result.stdout
    assert "--transform-force-phys" in result.stdout
    assert "--directed-force-phys" in result.stdout
