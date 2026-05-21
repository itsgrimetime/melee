"""Verification helpers for source-shape candidates."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .source_shape import CandidatePatch, CandidateScore, rank_scores


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
