"""Tests for candidate verification helpers."""
from __future__ import annotations

from pathlib import Path

from src.mwcc_debug.candidate_verify import (
    CheckdiffResult,
    parse_checkdiff_json,
    stage_patch,
    verify_patches,
    verify_real_tree_patches,
)
from src.mwcc_debug import source_shape
from src.mwcc_debug.source_shape import CandidatePatch


def test_stage_patch_writes_base_c(tmp_path: Path) -> None:
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) {}\n",
        summary="introduce temp",
        touched_ranges=((1, 2),),
    )
    staged = stage_patch(tmp_path, "fn_test", patch)
    assert staged.source_path.exists()
    assert staged.source_path.name == "base.c"
    assert staged.source_path.read_text() == "void f(void) {}\n"


def test_parse_checkdiff_json_reads_match_percent_and_delta() -> None:
    payload = '{"function": "fn", "fuzzy_match_percent": 97.5, "delta": 0.25}'
    parsed = parse_checkdiff_json(payload)
    assert parsed == CheckdiffResult(match_pct=97.5, delta=0.25)


def test_verify_patches_uses_runner_and_returns_scores(tmp_path: Path) -> None:
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) {}\n",
        summary="introduce temp",
        touched_ranges=((1, 2),),
    )

    def runner(candidate: CandidatePatch, staged_source: Path) -> CheckdiffResult:
        assert candidate.candidate_id == "arg-temp-0001"
        assert staged_source.exists()
        return CheckdiffResult(match_pct=98.0, delta=0.1)

    scores = verify_patches(
        function="fn_test",
        patches=[patch],
        stage_root=tmp_path,
        checkdiff_runner=runner,
    )
    assert len(scores) == 1
    assert scores[0].candidate_id == "arg-temp-0001"
    assert scores[0].compile_ok is True
    assert scores[0].checkdiff_delta == 0.1


def test_verify_real_tree_restores_source(tmp_path: Path) -> None:
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )

    def runner(function: str) -> CheckdiffResult:
        assert function == "fn_test"
        assert "Candidate" in source_path.read_text()
        return CheckdiffResult(match_pct=90.0, delta=0.1)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
    )
    assert scores[0].checkdiff_delta == 0.1
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_records_runner_error_and_continues(tmp_path: Path) -> None:
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )

    def runner(function: str) -> CheckdiffResult:
        raise RuntimeError("checkdiff timed out after 5s: python tools/checkdiff.py fn")

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        diagnostics_root=tmp_path / "diagnostics",
    )

    assert len(scores) == 1
    assert scores[0].compile_ok is False
    assert scores[0].diagnostics_path is not None
    assert "checkdiff timed out" in scores[0].diagnostics_path.read_text()
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_computes_delta_from_baseline_result(tmp_path: Path) -> None:
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )

    def runner(function: str) -> CheckdiffResult:
        assert function == "fn_test"
        return CheckdiffResult(match_pct=97.25, delta=None)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        baseline_result=CheckdiffResult(match_pct=97.25, delta=None),
    )

    assert scores[0].checkdiff_baseline_pct == 97.25
    assert scores[0].checkdiff_pct == 97.25
    assert scores[0].checkdiff_delta == 0.0
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_attaches_copy_trace_results(tmp_path: Path) -> None:
    assert hasattr(source_shape, "CandidateCopyTrace")
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="arg-temp-0001",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )
    trace = source_shape.CandidateCopyTrace(
        from_virtual=50,
        to_virtual=110,
        status="copy-found",
        likely_cause="removed-before-coloring",
    )

    def runner(function: str) -> CheckdiffResult:
        return CheckdiffResult(match_pct=97.25, delta=0.0)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        copy_trace_runner=lambda candidate: [trace],
    )

    assert scores[0].copy_traces == (trace,)
    assert source_path.read_text() == "void f(void) { Original(); }\n"


def test_verify_real_tree_preserves_copy_trace_summary_counts(tmp_path: Path) -> None:
    assert hasattr(source_shape, "CandidateCopyTraceSet")
    source_path = tmp_path / "file.c"
    source_path.write_text("void f(void) { Original(); }\n")
    patch = CandidatePatch(
        candidate_id="hidden-dirty-arg-temp-group-0004",
        patched_source="void f(void) { Candidate(); }\n",
        summary="candidate",
        touched_ranges=((1, 2),),
    )
    trace = source_shape.CandidateCopyTrace(
        from_virtual=50,
        to_virtual=110,
        status="copy-found",
        likely_cause="removed-before-coloring",
        interest_reasons=("dominant-source-virtual",),
    )
    noisy_trace = source_shape.CandidateCopyTrace(
        from_virtual=70,
        to_virtual=120,
        status="copy-found",
        likely_cause="removed-before-coloring",
    )
    trace_set = source_shape.CandidateCopyTraceSet(
        traces=(trace,),
        total_count=2,
        raw_traces=(trace, noisy_trace),
    )

    def runner(function: str) -> CheckdiffResult:
        return CheckdiffResult(match_pct=97.25, delta=0.0)

    scores = verify_real_tree_patches(
        function="fn_test",
        source_path=source_path,
        patches=[patch],
        checkdiff_runner=runner,
        apply_best=False,
        threshold=0.05,
        copy_trace_runner=lambda candidate: trace_set,
    )

    assert scores[0].copy_trace_highlights == (trace,)
    assert scores[0].copy_traces == (trace, noisy_trace)
    assert scores[0].copy_trace_total_count == 2
    assert scores[0].copy_trace_omitted_count == 1
