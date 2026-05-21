"""Verification helpers for source-shape candidates."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .source_shape import (
    CandidateCopyTrace,
    CandidateCopyTraceSet,
    CandidatePatch,
    CandidateScore,
    rank_scores,
)


@dataclass(frozen=True)
class StagedCandidate:
    candidate_id: str
    seed_dir: Path
    source_path: Path


@dataclass(frozen=True)
class CheckdiffResult:
    match_pct: Optional[float]
    delta: Optional[float]


CheckdiffRunner = Callable[[CandidatePatch, Path], CheckdiffResult]
CopyTraceRunner = Callable[
    [CandidatePatch],
    list[CandidateCopyTrace] | CandidateCopyTraceSet,
]


def stage_patch(stage_root: Path, function: str, patch: CandidatePatch) -> StagedCandidate:
    seed_dir = stage_root / function / patch.candidate_id
    seed_dir.mkdir(parents=True, exist_ok=True)
    source_path = seed_dir / "base.c"
    source_path.write_text(patch.patched_source)
    return StagedCandidate(
        candidate_id=patch.candidate_id,
        seed_dir=seed_dir,
        source_path=source_path,
    )


def parse_checkdiff_json(text: str) -> CheckdiffResult:
    payload = json.loads(text)
    match_pct = payload.get("fuzzy_match_percent")
    if match_pct is None:
        match_pct = payload.get("match_pct")
    delta = payload.get("delta")
    return CheckdiffResult(match_pct=match_pct, delta=delta)


def verify_patches(
    *,
    function: str,
    patches: list[CandidatePatch],
    stage_root: Path,
    checkdiff_runner: CheckdiffRunner,
) -> list[CandidateScore]:
    scores: list[CandidateScore] = []
    for patch in patches:
        staged = stage_patch(stage_root, function, patch)
        try:
            result = checkdiff_runner(patch, staged.source_path)
            scores.append(CandidateScore(
                candidate_id=patch.candidate_id,
                compile_ok=True,
                checkdiff_pct=result.match_pct,
                checkdiff_delta=result.delta,
                pcdump_score_delta=None,
                diagnostics_path=None,
                candidate_size=len(patch.patched_source.splitlines()),
                helper_param_count=0,
            ))
        except Exception as exc:
            log_path = staged.seed_dir / "verify_error.txt"
            log_path.write_text(f"{type(exc).__name__}: {exc}\n")
            scores.append(CandidateScore(
                candidate_id=patch.candidate_id,
                compile_ok=False,
                checkdiff_pct=None,
                checkdiff_delta=None,
                pcdump_score_delta=None,
                diagnostics_path=log_path,
                candidate_size=len(patch.patched_source.splitlines()),
                helper_param_count=0,
            ))
    return rank_scores(scores)


RealTreeCheckdiffRunner = Callable[[str], CheckdiffResult]


def verify_real_tree_patches(
    *,
    function: str,
    source_path: Path,
    patches: list[CandidatePatch],
    checkdiff_runner: RealTreeCheckdiffRunner,
    apply_best: bool,
    threshold: float,
    diagnostics_root: Optional[Path] = None,
    baseline_result: Optional[CheckdiffResult] = None,
    copy_trace_runner: Optional[CopyTraceRunner] = None,
) -> list[CandidateScore]:
    original = source_path.read_text()
    scores: list[CandidateScore] = []
    best_patch: Optional[CandidatePatch] = None
    best_delta = threshold
    baseline_pct = baseline_result.match_pct if baseline_result else None
    try:
        for patch in patches:
            source_path.write_text(patch.patched_source)
            try:
                result = checkdiff_runner(function)
                checkdiff_delta = result.delta
                if (
                    checkdiff_delta is None
                    and result.match_pct is not None
                    and baseline_pct is not None
                ):
                    checkdiff_delta = result.match_pct - baseline_pct
                score_delta = (
                    checkdiff_delta
                    if checkdiff_delta is not None else -9999.0
                )
                if score_delta >= best_delta:
                    best_delta = score_delta
                    best_patch = patch
                copy_traces: tuple[CandidateCopyTrace, ...] = ()
                copy_trace_highlights: tuple[CandidateCopyTrace, ...] = ()
                copy_trace_total_count = 0
                copy_trace_omitted_count = 0
                if copy_trace_runner is not None:
                    try:
                        trace_result = copy_trace_runner(patch)
                        if isinstance(trace_result, CandidateCopyTraceSet):
                            trace_set = trace_result
                            copy_trace_highlights = trace_set.traces
                            copy_traces = trace_set.raw_traces or trace_set.traces
                            copy_trace_total_count = trace_set.total_count
                            copy_trace_omitted_count = trace_set.omitted_count
                        else:
                            copy_traces = tuple(trace_result)
                            copy_trace_total_count = len(copy_traces)
                    except Exception as exc:
                        copy_traces = (CandidateCopyTrace(
                            from_virtual=None,
                            to_virtual=None,
                            status="trace-error",
                            likely_cause="trace-error",
                            note=f"{type(exc).__name__}: {exc}",
                        ),)
                        copy_trace_highlights = copy_traces
                        copy_trace_total_count = 1
                scores.append(CandidateScore(
                    candidate_id=patch.candidate_id,
                    compile_ok=True,
                    checkdiff_pct=result.match_pct,
                    checkdiff_delta=checkdiff_delta,
                    pcdump_score_delta=None,
                    diagnostics_path=None,
                    checkdiff_baseline_pct=baseline_pct,
                    candidate_size=len(patch.patched_source.splitlines()),
                    helper_param_count=0,
                    copy_traces=copy_traces,
                    copy_trace_highlights=copy_trace_highlights,
                    copy_trace_total_count=copy_trace_total_count,
                    copy_trace_omitted_count=copy_trace_omitted_count,
                ))
            except Exception as exc:
                log_path = None
                if diagnostics_root is not None:
                    diag_dir = diagnostics_root / patch.candidate_id
                    diag_dir.mkdir(parents=True, exist_ok=True)
                    log_path = diag_dir / "verify_error.txt"
                    log_path.write_text(f"{type(exc).__name__}: {exc}\n")
                scores.append(CandidateScore(
                    candidate_id=patch.candidate_id,
                    compile_ok=False,
                    checkdiff_pct=None,
                    checkdiff_delta=None,
                    pcdump_score_delta=None,
                    diagnostics_path=log_path,
                    checkdiff_baseline_pct=baseline_pct,
                    candidate_size=len(patch.patched_source.splitlines()),
                    helper_param_count=0,
                ))
    finally:
        if apply_best and best_patch is not None:
            source_path.write_text(best_patch.patched_source)
        else:
            source_path.write_text(original)
    return rank_scores(scores)
