"""Tests for search artifact contract (pure dataclasses)."""

from pathlib import Path
from src.search.artifact import (
    CompileSpec,
    CompileManifest,
    Provenance,
    CandidateArtifact,
    compute_candidate_id,
)


def _spec(tmp_path) -> CompileSpec:
    return CompileSpec(
        target_id="MatToQuat@quatlib",
        cflags_hash="cf",
        base_context_hash="bc",
        toolchain_fingerprint="tc",
        backend_mode="plain-local",
        manifest_path=tmp_path / "manifest.json",
    )


def test_candidate_id_includes_full_compile_context(tmp_path):
    """Candidate ID must change if any part of compile context changes."""
    spec_a = _spec(tmp_path)
    spec_b = CompileSpec(**{**spec_a.__dict__, "cflags_hash": "DIFFERENT"})
    assert compute_candidate_id(spec_a, "srchash") != compute_candidate_id(spec_b, "srchash")
    assert compute_candidate_id(spec_a, "srchash") == compute_candidate_id(spec_a, "srchash")


def test_artifact_is_frozen_and_round_trip_fields_present(tmp_path):
    """CandidateArtifact must be frozen and preserve all fields."""
    art = CandidateArtifact(
        candidate_id="id",
        source_hash="sh",
        source_blob=tmp_path / "s.c",
        compile_spec=_spec(tmp_path),
        object_path=None,
        producer_score=12.0,
        byte_score=None,
        directed_score=None,
        pcdump_path=None,
        compiler_stderr="",
        provenance=Provenance("permuter", None, None, "base", {}),
        status="harvested",
    )
    assert art.status == "harvested" and art.object_path is None and art.producer_score == 12.0

    import dataclasses
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        art.byte_score = 5
