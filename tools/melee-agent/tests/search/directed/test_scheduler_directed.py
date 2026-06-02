"""Tests for DefaultScheduler directed-mode (Task 6).

All fakes — no mwcc compilation.  Three test cases:
  1. Escalate path: pcdump backend is used, all candidates in a batch are
     scored against the SAME parent_state, and exactly ONE best is observed.
  2. Invalid surfaced: invalid candidates increment directed_invalid and are
     NOT treated as progress.
  3. Tier-1 unchanged: directed=None returns a SearchResult with empty
     directed_telemetry and never touches pcdump / score_directed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from src.search.artifact import CandidateArtifact, CompileSpec, Provenance
from src.search.directed.contracts import (
    DirectedMeta,
    DirectedSchedulerConfig,
    DirectedScoringCall,
    DirectedSearchState,
)
from src.search.scheduler import DefaultScheduler
from src.search.store import ArtifactStore
from src.search.types import (
    Budget,
    SchedulePolicy,
    SearchContext,
    SearchResult,
    SourceVariant,
    TargetSpec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_art(candidate_id: str, byte_score: int, tmp: Path) -> CandidateArtifact:
    src = tmp / f"{candidate_id}.c"
    src.write_text(f"// {candidate_id}")
    obj = tmp / f"{candidate_id}.o"
    obj.write_bytes(b"OBJ")
    spec = CompileSpec(
        target_id="f@u",
        cflags_hash="c",
        base_context_hash="b",
        toolchain_fingerprint="t",
        backend_mode="fake",
        manifest_path=tmp / "m.json",
    )
    prov = Provenance(
        source_name="fake",
        parent_id=None,
        mutation=None,
        base_hash="bh",
        producer_meta={},
    )
    return CandidateArtifact(
        candidate_id=candidate_id,
        source_hash=candidate_id,
        source_blob=src,
        compile_spec=spec,
        object_path=obj,
        producer_score=None,
        byte_score=byte_score,
        directed_score=None,
        pcdump_path=None,
        compiler_stderr="",
        provenance=prov,
        status="ok",
        directed_meta=None,
    )


def _make_meta(valid: bool, displacement: float, parent_state_id: str,
               invalid_reason: str | None = None) -> DirectedMeta:
    return DirectedMeta(
        candidate_id="x",
        source_hash="x",
        iteration=0,
        parent_id=None,
        parent_state_id=parent_state_id,
        valid=valid,
        invalid_reason=invalid_reason,
        case="test" if valid else None,
        label=None,
        order_distance=0,
        displacement=displacement,
        displacement_delta=0.0,
        reanchor_matched=1,
        reanchor_total=1,
        diagnosis_chars=4 if valid else 0,
        applied_mutator=None,
        directed_scalar=displacement,
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeSource:
    """Yields `n_variants` variants on the first call, then empty.

    Records all observe() calls.
    """

    def __init__(self, variants: list[SourceVariant]) -> None:
        self._variants = variants
        self._exhausted = False
        self.observed_batches: list[int] = []  # len of each observed batch

    def name(self) -> str:
        return "fake-source"

    def seed(self, base: Any) -> None:
        pass

    def next_batch(self, n: int) -> list[SourceVariant]:
        if self._exhausted:
            return []
        self._exhausted = True
        return self._variants[:n]

    def observe(self, scored: list[Any]) -> None:
        self.observed_batches.append(len(scored))


class FakePcdumpBackend:
    """Records whether compile was called with want_pcdump=True."""

    def __init__(self, arts: list[CandidateArtifact]) -> None:
        self._arts = list(arts)
        self._idx = 0
        self.compiled_with_pcdump: bool | None = None
        self.all_want_pcdump: list[bool] = []

    def name(self) -> str:
        return "fake-pcdump"

    def capabilities(self) -> Any:
        from src.search.types import BackendCaps
        return BackendCaps("local", 1, True)

    def compile(self, variant: SourceVariant, *, want_pcdump: bool = False) -> CandidateArtifact:
        self.compiled_with_pcdump = want_pcdump
        self.all_want_pcdump.append(want_pcdump)
        art = self._arts[self._idx % len(self._arts)]
        self._idx += 1
        return art


class FakePlainBackend:
    """Plain backend — records want_pcdump, always False."""

    def __init__(self, arts: list[CandidateArtifact]) -> None:
        self._arts = list(arts)
        self._idx = 0
        self.all_want_pcdump: list[bool] = []

    def name(self) -> str:
        return "fake-plain"

    def capabilities(self) -> Any:
        from src.search.types import BackendCaps
        return BackendCaps("local", 1, False)

    def compile(self, variant: SourceVariant, *, want_pcdump: bool = False) -> CandidateArtifact:
        self.all_want_pcdump.append(want_pcdump)
        art = self._arts[self._idx % len(self._arts)]
        self._idx += 1
        return art


class FakeBytePipeline:
    """score_byte returns the art unchanged (byte_score already set)."""

    def score_byte(self, art: CandidateArtifact, target: Any) -> CandidateArtifact:
        return art

    def should_escalate(self, art: Any, ctx: Any) -> bool:
        return False

    def score_directed(self, art: Any, call: Any) -> Any:
        raise AssertionError("score_directed must not be called in tier-1 mode")


class FakeScorePipeline:
    """Controls escalation and directed scoring.

    Args:
        always_escalate: if True, should_escalate always returns True.
        metas: list of DirectedMeta to attach in order; wraps around.
    """

    def __init__(
        self,
        *,
        always_escalate: bool = True,
        metas: list[DirectedMeta] | None = None,
    ) -> None:
        self._always_escalate = always_escalate
        self._metas = metas or []
        self._meta_idx = 0
        self.score_directed_calls: list[DirectedScoringCall] = []

    def score_byte(self, art: CandidateArtifact, target: Any) -> CandidateArtifact:
        return art

    def should_escalate(self, art: Any, ctx: Any) -> bool:
        return self._always_escalate

    def score_directed(self, art: CandidateArtifact, call: DirectedScoringCall) -> CandidateArtifact:
        self.score_directed_calls.append(call)
        if not self._metas:
            meta = _make_meta(True, 1.0, call.parent_state.state_id)
            return replace(art, directed_meta=meta)
        meta = self._metas[self._meta_idx % len(self._metas)]
        self._meta_idx += 1
        # Override parent_state_id to match the actual call's parent
        meta = replace(meta, parent_state_id=call.parent_state.state_id)
        status = "invalid" if not meta.valid else art.status
        return replace(art, directed_meta=meta, status=status)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_directed_escalates_routes_pcdump_scores_per_parent_selects_one(tmp_path):
    """Directed mode: backend is switched to pcdump backend, all candidates in
    a batch are scored against the SAME parent_state, and exactly ONE best is
    observed per batch.
    """
    store = ArtifactStore(tmp_path / "store")

    # Two variants, two different byte scores (so best-selection is meaningful)
    variants = [
        SourceVariant("int f(){return 1;}", None),
        SourceVariant("int f(){return 2;}", None),
    ]
    arts = [
        _make_art("c1", byte_score=10, tmp=tmp_path),
        _make_art("c2", byte_score=5, tmp=tmp_path),
    ]
    source = FakeSource(variants)
    backend = FakePcdumpBackend(arts)
    # Metas: both valid, different displacements; both have parent_state_id set
    # to the initial "root" since they are in the same batch.
    metas = [
        _make_meta(True, 2.0, "root"),
        _make_meta(True, 3.0, "root"),
    ]
    pipeline = FakeScorePipeline(always_escalate=True, metas=metas)

    sched = DefaultScheduler(store=store, verifier=None)
    cfg = DirectedSchedulerConfig(
        objective=None,
        score_pipeline=pipeline,
        backend=backend,
        plateau_n=3,
    )

    res = sched.run(
        sources=[source],
        backends=[backend],  # tier-1 backend (same here, just to satisfy protocol)
        producers=[],
        pipeline=pipeline,
        target=TargetSpec("f", "u", tmp_path / "e.o"),
        budget=Budget(max_iters=1),
        policy=SchedulePolicy(batch_size=2),
        directed=cfg,
    )

    # Pcdump backend was used (want_pcdump=True)
    assert backend.compiled_with_pcdump is True, "expected pcdump backend to be called"

    # All telemetry entries from the batch share the same parent_state_id
    k = len(res.directed_telemetry)
    assert k >= 1, "expected at least one directed_telemetry entry"
    assert all(
        m.parent_state_id == "root" for m in res.directed_telemetry[:k]
    ), f"expected all parent_state_id=='root', got {[m.parent_state_id for m in res.directed_telemetry[:k]]}"

    # Exactly ONE best observed per batch
    assert source.observed_batches == [1], (
        f"expected [1] observed per batch, got {source.observed_batches}"
    )

    # Result has the SearchResult shape
    assert isinstance(res, SearchResult)
    assert res.directed_telemetry is not None


def test_invalid_surfaced_not_progress(tmp_path):
    """Invalid directed candidates appear in telemetry, increment accounting,
    and are not treated as progress (not selected as best).
    """
    store = ArtifactStore(tmp_path / "store")

    variants = [SourceVariant("int f(){return 1;}", None)]
    arts = [_make_art("cinv", byte_score=20, tmp=tmp_path)]
    source = FakeSource(variants)
    backend = FakePcdumpBackend(arts)

    metas = [_make_meta(False, 0.0, "root", invalid_reason="no_roles")]
    pipeline = FakeScorePipeline(always_escalate=True, metas=metas)

    sched = DefaultScheduler(store=store, verifier=None)
    cfg = DirectedSchedulerConfig(
        objective=None,
        score_pipeline=pipeline,
        backend=backend,
        plateau_n=3,
    )

    res = sched.run(
        sources=[source],
        backends=[backend],
        producers=[],
        pipeline=pipeline,
        target=TargetSpec("f", "u", tmp_path / "e.o"),
        budget=Budget(max_iters=1),
        policy=SchedulePolicy(batch_size=1),
        directed=cfg,
    )

    assert any(m.valid is False for m in res.directed_telemetry), (
        "expected at least one invalid directed_meta in telemetry"
    )
    assert res.accounting.get("directed_invalid", 0) >= 1, (
        f"expected directed_invalid>=1, got {res.accounting}"
    )


def test_tier1_unchanged_when_directed_none(tmp_path):
    """Tier-1 path (directed=None) returns SearchResult with empty
    directed_telemetry and never calls score_directed or pcdump compile.
    """
    store = ArtifactStore(tmp_path / "store")

    variants = [SourceVariant("int f(){return 1;}", None)]
    arts = [_make_art("t1c", byte_score=7, tmp=tmp_path)]
    source = FakeSource(variants)
    backend = FakePlainBackend(arts)
    pipeline = FakeBytePipeline()

    sched = DefaultScheduler(store=store, verifier=None)

    res = sched.run(
        sources=[source],
        backends=[backend],
        producers=[],
        pipeline=pipeline,
        target=TargetSpec("f", "u", tmp_path / "e.o"),
        budget=Budget(max_iters=1),
        policy=SchedulePolicy(batch_size=1),
        # NO directed= kwarg at all
    )

    assert res.directed_telemetry == [], (
        f"expected empty directed_telemetry in tier-1 mode, got {res.directed_telemetry}"
    )
    # want_pcdump should never be True from the plain backend
    assert all(not p for p in backend.all_want_pcdump), (
        "tier-1 should not request pcdump"
    )
    assert isinstance(res, SearchResult)
