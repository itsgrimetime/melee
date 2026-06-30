"""Litmus test for SourceVariant abstraction with multiple source implementations."""

from pathlib import Path
from src.search.sources import SeedListSource
from src.search.scheduler import DefaultScheduler
from src.search.scoring import ByteScorePipeline
from src.search.store import ArtifactStore
from src.search.backends import PlainLocalBackend
from src.search.types import (
    TargetSpec,
    Budget,
    SchedulePolicy,
    SourceSpec,
    SourceVariant,
)
from src.search.artifact import CompileSpec
from tests.search.test_backends import FakeCompiler


def _spec(tmp):
    return CompileSpec("f@u", "c", "b", "t", "plain-local", tmp / "m.json")


class ConstSource:
    """The 'second source' — proves the abstraction (different shape than SeedListSource)."""

    def name(self):
        return "const"

    def seed(self, base):
        self._b = base

    def next_batch(self, n):
        return [SourceVariant("int f(){return 0;}", None)]

    def observe(self, scored):
        pass


def _run(tmp_path, source):
    store = ArtifactStore(tmp_path / "store")
    backend = PlainLocalBackend(
        compiler=FakeCompiler(tmp_path),
        store=store,
        compile_spec_factory=lambda v: _spec(tmp_path),
    )

    class S:
        def byte_distance(self, o, t):
            return 5

    sched = DefaultScheduler(store=store, verifier=None)
    source.seed(SourceSpec("base", TargetSpec("f", "u", tmp_path / "e.o")))
    return sched.run(
        sources=[source],
        backends=[backend],
        producers=[],
        pipeline=ByteScorePipeline(scorer=S()),
        target=TargetSpec("f", "u", tmp_path / "e.o"),
        budget=Budget(max_iters=1),
        policy=SchedulePolicy(),
    )


def test_seedlist_source_flows(tmp_path):
    res = _run(tmp_path, SeedListSource(["int f(){return 1;}", "int f(){return 2;}"]))
    assert res.accounting["compiled"] == 2 and len(res.best) == 2


def test_second_source_drops_in_with_no_engine_change(tmp_path):
    res = _run(tmp_path, ConstSource())
    assert res.accounting["compiled"] == 1 and res.best[0].byte_score == 5
