"""Tests for candidate verification helpers."""
from __future__ import annotations

from pathlib import Path

from src.mwcc_debug.candidate_verify import (
    CheckdiffResult,
    parse_checkdiff_json,
    stage_patch,
    verify_patches,
)
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
