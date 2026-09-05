"""Tests for search scoring pipeline and policies."""

from pathlib import Path
from src.search.scoring import ByteScorePipeline, DefaultSchedulePolicy
from src.search.types import TargetSpec, SearchContext
from src.search.artifact import CandidateArtifact, CompileSpec, Provenance


def _art(tmp_path, obj):
    return CandidateArtifact(
        "id",
        "sh",
        tmp_path / "s.c",
        CompileSpec("f@u", "c", "b", "t", "plain-local", tmp_path / "m.json"),
        obj,
        None,
        None,
        None,
        None,
        "",
        Provenance("seed", None, None, "base", {}),
        "ok",
    )


class FakeScorer:
    def byte_distance(self, obj_path, target):
        return 0 if obj_path and obj_path.name == "match.o" else 7


def test_score_byte_sets_score_from_scorer(tmp_path):
    pipe = ByteScorePipeline(scorer=FakeScorer())
    art = pipe.score_byte(_art(tmp_path, tmp_path / "x.o"), TargetSpec("f", "u", tmp_path / "e.o"))
    assert art.byte_score == 7


def test_score_byte_none_object_is_score_failed(tmp_path):
    pipe = ByteScorePipeline(scorer=FakeScorer())
    art = pipe.score_byte(_art(tmp_path, None), TargetSpec("f", "u", tmp_path / "e.o"))
    assert art.byte_score is None and art.status == "score_failed"


def test_should_escalate_false_in_spec1(tmp_path):
    pipe = ByteScorePipeline(scorer=FakeScorer())
    assert pipe.should_escalate(_art(tmp_path, tmp_path / "x.o"), SearchContext()) is False


def test_default_policy_values():
    assert DefaultSchedulePolicy().promote_top_k == 8
