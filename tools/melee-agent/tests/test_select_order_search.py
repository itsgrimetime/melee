"""Tests for select-order-directed source-shape search ranking."""

from __future__ import annotations

import json
import pathlib
import signal
import subprocess
import textwrap

import pytest
from typer.testing import CliRunner

import src.cli.debug as debug_cli
from src.cli import app
from src.mwcc_debug.cache import cache_path
from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe
from src.mwcc_debug.select_order_search import (
    rank_select_order_candidates,
    score_select_order_candidate,
)

runner = CliRunner()


BASELINE = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 33 1 1 0x00
        1 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 33 r30 1 1 0x00
          interferers: 32=r29
        1 32 r29 1 1 0x00
          interferers: 33=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")


TARGET_ORDER = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
        mr r33,r4
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
        1 33 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)
      iter ig_idx phys degree nIntfr flags
        0 32 r30 1 1 0x00
          interferers: 33=r29
        1 33 r29 1 1 0x00
          interferers: 32=r30
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")


def _write_stale_auto_cache(tmp_path: pathlib.Path) -> pathlib.Path:
    melee_root = tmp_path / "melee"
    source = melee_root / "src" / "melee" / "mn" / "sample.c"
    source.parent.mkdir(parents=True)
    source.write_text("void fn_80000000(void) {}\n", encoding="utf-8")
    cached = cache_path(melee_root, "melee/mn/sample")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(BASELINE, encoding="utf-8")
    cached.with_suffix(".hash").write_text("0" * 64 + "\n", encoding="ascii")
    return melee_root


MISSING_SECOND = textwrap.dedent("""\
    Starting function fn_80000000
    BEFORE REGISTER COLORING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        mr r32,r3
    SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=45)
      iter ig_idx degree arraySize flags notes
        0 32 1 1 0x00
    COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
      iter ig_idx phys degree nIntfr flags
        0 32 r30 1 1 0x00
    FINAL CODE AFTER INSTRUCTION SCHEDULING
    fn_80000000
    B0: Succ={} Pred={} Labels={}
        stwu r1,-48(r1)
        stmw r29,24(r1)
        blr
""")


def test_select_order_score_prioritizes_requested_order() -> None:
    wrong = score_select_order_candidate(
        BASELINE,
        BASELINE,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=99.0,
    )
    right = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=12.0,
    )

    ranked = rank_select_order_candidates([
        {"label": "high-match-wrong-order", "status": "ok", "objective": wrong.to_dict()},
        {"label": "select-order-flipped", "status": "ok", "objective": right.to_dict()},
    ])

    assert ranked[0]["label"] == "select-order-flipped"
    assert ranked[0]["objective"]["target_order_satisfied"] is True
    assert ranked[0]["objective"]["target_order_improved"] is True
    assert ranked[0]["objective"]["target_orders"][0]["candidate_satisfied"] is True


def test_select_order_score_marks_missing_target_side_actionable() -> None:
    objective = score_select_order_candidate(
        BASELINE,
        MISSING_SECOND,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=10.0,
    )

    pair = objective.to_dict()["target_orders"][0]
    assert pair["candidate_missing_virtuals"] == [33]
    assert pair["candidate_present_count"] == 1
    assert pair["distance_to_flip"] == 2
    assert pair["actionable_movement"] is True
    assert objective.to_dict()["actionable_movement_count"] == 1


def test_select_order_ranking_prefers_actionable_missing_side_over_unchanged() -> None:
    wrong = score_select_order_candidate(
        BASELINE,
        BASELINE,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=99.0,
    )
    missing = score_select_order_candidate(
        BASELINE,
        MISSING_SECOND,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=12.0,
    )
    right = score_select_order_candidate(
        BASELINE,
        TARGET_ORDER,
        function="fn_80000000",
        target_orders=[(32, 33)],
        match_percent=1.0,
    )

    ranked = rank_select_order_candidates([
        {
            "label": "high-match-wrong-order",
            "status": "ok",
            "objective": wrong.to_dict(),
        },
        {
            "label": "missing-target-side",
            "status": "ok",
            "objective": missing.to_dict(),
        },
        {
            "label": "select-order-flipped",
            "status": "ok",
            "objective": right.to_dict(),
        },
    ])

    assert [row["label"] for row in ranked] == [
        "select-order-flipped",
        "missing-target-side",
        "high-match-wrong-order",
    ]


def test_select_order_search_cli_ranks_candidate_pcdumps_json(
    tmp_path: pathlib.Path,
) -> None:
    baseline = tmp_path / "baseline.txt"
    unchanged = tmp_path / "unchanged.txt"
    target_order = tmp_path / "target-order.txt"
    baseline.write_text(BASELINE)
    unchanged.write_text(BASELINE)
    target_order.write_text(TARGET_ORDER)

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"high-match-wrong-order:noop={unchanged}",
            "--candidate",
            f"select-order-flipped:block-scope={target_order}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["target_orders"] == [[32, 33]]
    assert payload["ranking"] == "target select-order objective, final match percent tiebreaker"
    assert payload["variants"][0]["label"] == "select-order-flipped"
    assert payload["variants"][0]["objective"]["target_order_satisfied"] is True
    assert payload["variants"][1]["label"] == "high-match-wrong-order"


def test_select_order_search_rejects_stale_auto_cache_by_default(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = _write_stale_auto_cache(tmp_path)
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 4
    assert "cached pcdump is stale" in result.stdout + result.stderr
    assert "--allow-stale-pcdump" in result.stdout + result.stderr


def test_select_order_search_allow_stale_auto_cache_reports_timestamps(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = _write_stale_auto_cache(tmp_path)
    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        lambda *args, **kwargs: [],
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--allow-stale-pcdump",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    baseline_cache = payload["baseline_cache"]
    assert baseline_cache["fresh"] is False
    assert baseline_cache["path"].endswith("build/mwcc_debug_cache/melee/mn/sample.txt")
    assert baseline_cache["source_path"].endswith("src/melee/mn/sample.c")
    assert isinstance(baseline_cache["source_mtime"], float)
    assert isinstance(baseline_cache["cache_mtime"], float)


def test_select_order_search_includes_probe_provenance_and_match_score(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(*args, **kwargs) -> tuple[float | None, str | None]:
        return 87.25, None

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"call-chain:call-return-compare-switch={source}",
            "--probe-provenance",
            json.dumps({
                "kind": "call-return-compare-chain",
                "call_symbol": "helper_call",
                "call_expression": "helper_call(entity)",
                "result_var": "b34_result",
                "compare_var": "b34",
                "compare_values": [1, 0],
                "source_line": 6,
                "source_col": 18,
            }),
            "--score-match-percent",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["probe"]["provenance"]["call_symbol"] == "helper_call"
    assert variant["probe"]["provenance"]["compare_values"] == [1, 0]
    assert variant["objective"]["match_percent"] == 87.25


def test_select_order_search_scores_generated_probe_match_percent_by_default(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")
    calls: list[pathlib.Path] = []

    def fake_probes(*args, **kwargs) -> list[LifetimeLayoutProbe]:
        return [
            LifetimeLayoutProbe(
                label="generated-probe-0",
                operator="call-return-compare-chain",
                description="Synthetic generated probe.",
                source_text="void fn_80000000(void) {}\n",
            )
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        calls.append(path)
        return 91.5, None

    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["label"] == "generated-probe-0"
    assert variant["objective"]["match_percent"] == 91.5
    assert len(calls) == 1
    assert calls[0].name == "generated-probe-0.c"


def test_select_order_signal_restore_handler_restores_active_source(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "sample.c"
    source.write_text("void fn_80000000(void) { /* original */ }\n")

    debug_cli._ACTIVE_SOURCE_RESTORES.clear()
    debug_cli._register_active_source_restore(source, source.read_text())
    source.write_text("void fn_80000000(void) { /* mutated */ }\n")

    with pytest.raises(SystemExit) as excinfo:
        debug_cli._restore_active_sources_for_signal(signal.SIGTERM, None)

    assert excinfo.value.code == 128 + signal.SIGTERM
    assert source.read_text() == "void fn_80000000(void) { /* original */ }\n"
    assert source not in debug_cli._ACTIVE_SOURCE_RESTORES


def test_select_order_source_match_percent_restores_after_compile_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    target = melee_root / "src" / "melee" / "mn" / "sample.c"
    target.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    target.write_text(original)
    candidate = tmp_path / "candidate.c"
    candidate.write_text("void fn_80000000(void) { /* candidate */ }\n")

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(
        debug_cli,
        "_run_ninja_with_no_diag_retry",
        lambda *args, **kwargs: (
            subprocess.CompletedProcess(
                ["ninja", "build/GALE01/src/melee/mn/sample.o"],
                124,
                "",
                "timed out after 1s",
            ),
            False,
        ),
    )
    monkeypatch.setattr(
        debug_cli.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    pct, error = debug_cli._select_order_source_match_percent(
        candidate,
        function="fn_80000000",
        melee_root=melee_root,
        timeout=1,
    )

    assert pct is None
    assert error is not None
    assert "timed out after 1s" in error
    assert target.read_text() == original


def test_select_order_source_match_percent_holds_repo_lock_through_restore(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    melee_root = tmp_path / "melee"
    target = melee_root / "src" / "melee" / "mn" / "sample.c"
    target.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { /* original */ }\n"
    candidate_text = "void fn_80000000(void) { /* candidate */ }\n"
    target.write_text(original)
    candidate = tmp_path / "candidate.c"
    candidate.write_text(candidate_text)
    events: list[str] = []
    lock_held = False

    class FakeLock:
        def __enter__(self):
            nonlocal lock_held
            events.append("lock-enter")
            lock_held = True

        def __exit__(self, exc_type, exc, tb):
            nonlocal lock_held
            assert target.read_text() == original
            events.append("lock-exit")
            lock_held = False

    def fake_lock(root: pathlib.Path, *, label: str = ""):
        assert root == melee_root
        assert label == "source-scoring"
        return FakeLock()

    def fake_ninja(*args, **kwargs):
        assert lock_held is True
        assert target.read_text() == candidate_text
        events.append("ninja")
        return (
            subprocess.CompletedProcess(args[0], 0, "", ""),
            False,
        )

    def fake_refresh(*args, **kwargs):
        assert lock_held is True
        assert target.read_text() == candidate_text
        events.append("report")
        return 97.5, None

    def fake_cleanup(*args, **kwargs):
        assert lock_held is True
        assert target.read_text() == original
        events.append("cleanup")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli, "_acquire_checkdiff_repo_lock", fake_lock)
    monkeypatch.setattr(debug_cli, "_run_ninja_with_no_diag_retry", fake_ninja)
    monkeypatch.setattr(debug_cli, "_refresh_match_pct_after_successful_build", fake_refresh)
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_cleanup)

    pct, error = debug_cli._select_order_source_match_percent(
        candidate,
        function="fn_80000000",
        melee_root=melee_root,
        timeout=1,
    )

    assert pct == 97.5
    assert error is None
    assert events == ["lock-enter", "ninja", "report", "cleanup", "lock-exit"]
    assert target.read_text() == original


def test_refresh_match_percent_reports_objdiff_timeout(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    objdiff = tmp_path / "build" / "tools" / "objdiff-cli"
    objdiff.parent.mkdir(parents=True)
    objdiff.write_text("#!/bin/sh\n")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    pct, error = debug_cli._refresh_match_pct_after_successful_build(
        "melee/mn/sample",
        "fn_80000000",
        tmp_path,
        timeout=3,
    )

    assert pct is None
    assert error is not None
    assert "timed out after 3s running" in error
    assert "objdiff-cli report generate" in error


def test_select_order_search_beam_composes_and_ranks_by_real_score(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "sample.c"
    campaign = tmp_path / "campaign"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) { /* seed */ }\n")

    def fake_probes(source_text: str, *args, **kwargs) -> list[LifetimeLayoutProbe]:
        if "neutral" in source_text:
            return [
                LifetimeLayoutProbe(
                    label="compose-win",
                    operator="block-scope",
                    description="Compose with the neutral probe.",
                    source_text=(
                        "void fn_80000000(void) { /* seed neutral win */ }\n"
                    ),
                )
            ]
        return [
            LifetimeLayoutProbe(
                label="neutral",
                operator="call-return-compare-chain",
                description="Neutral first step.",
                source_text="void fn_80000000(void) { /* seed neutral */ }\n",
            ),
            LifetimeLayoutProbe(
                label="regression",
                operator="call-return-compare-chain",
                description="Regressing first step.",
                source_text="void fn_80000000(void) { /* seed regression */ }\n",
            ),
            LifetimeLayoutProbe(
                label="duplicate-neutral",
                operator="call-return-compare-chain",
                description="Duplicate body.",
                source_text="void fn_80000000(void) { /* seed neutral */ }\n",
            ),
        ]

    def fake_compile(*args, **kwargs) -> str:
        return TARGET_ORDER

    def fake_match_percent(
        path: pathlib.Path,
        **kwargs,
    ) -> tuple[float | None, str | None]:
        text = path.read_text()
        if "win" in text:
            return 98.0, None
        if "neutral" in text:
            return 97.37545, None
        return 70.0, None

    monkeypatch.setattr(
        "src.mwcc_debug.pressure_explorer.generate_lifetime_layout_probes",
        fake_probes,
    )
    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )
    monkeypatch.setattr(
        "src.cli.debug._select_order_source_match_percent",
        fake_match_percent,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--source-file",
            str(source),
            "--beam-depth",
            "2",
            "--beam-width",
            "1",
            "--campaign-dir",
            str(campaign),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ranking"] == (
        "final match percent first, then target select-order objective"
    )
    assert payload["beam_campaign_dir"] == str(campaign)
    ledger = json.loads((campaign / "ledger.json").read_text())
    assert ledger["beam_depth"] == 2
    assert ledger["beam_width"] == 1
    assert len(ledger["deduped"]) == 1
    labels = [entry["label"] for entry in ledger["entries"]]
    assert any("neutral" in label for label in labels)
    assert any("compose-win" in label for label in labels)

    variants = payload["variants"]
    assert variants[0]["chain"] == ["neutral", "compose-win"]
    assert variants[0]["objective"]["match_percent"] == 98.0
    assert variants[1]["chain"] == ["neutral"]
    assert variants[1]["objective"]["match_percent"] == 97.37545


def test_select_order_search_marks_source_pcdump_omission_as_build_failed(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    baseline = tmp_path / "baseline.txt"
    source = tmp_path / "bad-probe.c"
    baseline.write_text(BASELINE)
    source.write_text("void fn_80000000(void) {}\n")

    def fake_compile(*args, **kwargs) -> str:
        return BASELINE.replace("fn_80000000", "other_fn")

    monkeypatch.setattr(
        "src.mwcc_debug.diff_capture.compile_source_variant",
        fake_compile,
    )

    result = runner.invoke(
        app,
        [
            "debug",
            "select-order-search",
            "-f",
            "fn_80000000",
            "--target",
            "r32<r33",
            "--pcdump",
            str(baseline),
            "--candidate",
            f"bad-source:declaration-use-distance={source}",
            "--no-compile-probes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    variant = json.loads(result.stdout)["variants"][0]
    assert variant["status"] == "build-failed"
    assert "fn_80000000 not found in pcdump" in variant["error"]
    assert variant["source_retained"] == str(source)
    assert "objective" not in variant


def test_select_order_search_help_smoke() -> None:
    result = runner.invoke(app, ["debug", "select-order-search", "--help"])

    assert result.exit_code == 0
    assert "--target" in result.stdout
